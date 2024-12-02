import base64, datetime, os, requests
from types import SimpleNamespace
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
import github
from ..models import GITHUB_PREFIX
from ..util import *
from missions import plugins


# these all could be per-customer parameters
RECENT_DAYS = 14
MAX_OPEN_PRS = 100
MAX_PRS = 200
MAX_CLOSED_PRS = 50
MAX_OPEN_ISSUES = 100
MAX_CLOSED_ISSUES = 50
TRUNCATE_DEFAULT = 1600  # characters of any given comment to fetch
OPEN_PR_HYDRATE_CUTOFF = 20  # how many open PRs to get comments/files/changes for
CLOSED_PR_HYDRATE_CUTOFF = 5  # how many closed PRs to get comments/files/changes for
OPEN_ISSUE_HYDRATE_CUTOFF = 20  # how many open issues to get comments for
CLOSED_ISSUE_HYDRATE_CUTOFF = 5  # how many closed issues to get comments for
COMMIT_HYDRATE_CUTOFF = 80  # get details for this many non-trivial commits
COMMIT_INTEREST_CUTOFF = 90  # how many days back to get files/changes for
MAX_COMMITS = 200
MAX_BRANCHES_TO_CONSIDER = 200  # we can't deal with thousands and thousands
MAX_BRANCHES = 100  # we order the branches chronologically
MAX_BRANCH_COMMITS = 40
MAX_PR_COMMITS = 100
MAX_COMMENTS = 10
MAX_REVIEW_COMMENTS = 20
BRANCH_HYDRATE_CUTOFF = 3  # how many commits to hydrate for side branches
BRANCH_HYDRATE_DAYS = 60  # how many days before we ignore side branches
MAX_PR_BODY_LENGTH = 16000
OBSOLETE_CLOSED_PR_DAYS = 180
MAX_FILES_TO_SHOW = 32

# https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/about-authentication-with-a-github-app
# https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation


@plugins.hookimpl
def run_api(task):
    if task.url and task.url.startswith(GITHUB_PREFIX):
        repo = get_gh_repo(task)
        method = task.url.replace(GITHUB_PREFIX, "").split("/")[2]
        method = method.replace("README.md", "README").lower()

        match method:
            case "readme":
                get_gh_readme(task, repo)
                return task

            case "commits":
                get_gh_commits(task, repo)
                return task

            case "issues":
                get_gh_issues(task, repo)
                return task

            case "pulls":
                get_gh_pulls(task, repo)
                return task

            case "actions":
                get_gh_actions(task, repo)
                return task
    return None


def get_source_id(task):
    vendor = "github"
    integration = None
    # for the rare-outside-testing case of projects with both the full and metadata-only integrations
    if task.github_metadata_only():
        vendor = "github2"
        integration = task.get_integration(vendor)
    if not integration:
        vendor = "github"
        integration = task.get_integration(vendor)
    if not integration:
        return None
    secret = integration.secret_set.filter(vendor=vendor).last()
    return secret.value if secret else integration.extras.get("install_id")


def auth_github(task):
    if task and task.get_customer() and get_source_id(task):
        id = int(os.environ["GITHUB_APP_ID"])
        key = base64.b64decode(os.environ["GITHUB_APP_KEY"]).decode("utf-8")
        if task.github_metadata_only():
            id = int(os.environ["GITHUB_APP_ID_2"])
            key = base64.b64decode(os.environ["GITHUB_APP_KEY_2"]).decode("utf-8")
        app_auth = github.Auth.AppAuth(id, key)
        installation_id = int(get_source_id(task))
        return app_auth.get_installation_auth(installation_id)
    else:
        token = os.environ["GITHUB_TOKEN"]
        if not token:
            log("WARNING: No GitHub token found")
        return github.Auth.Token(token)


def get_gh_repo(task, repo=None):
    if not repo:
        repo = task.get_repo()
    if not repo:
        path = task.url.replace(GITHUB_PREFIX, "")
        elements = path.split("/")
        repo = "/".join(elements[:2])

    auth = auth_github(task)
    gh = github.Github(
        auth=auth,
        user_agent="PyGitHub/Python|YamLLMs|info@" + settings.BASE_DOMAIN,
        per_page=100,
    )
    log("GitHub rate limit", gh.get_rate_limit().remaining)
    try:
        api = gh.get_repo(repo)
        return api
    except Exception as ex:
        task.extras["fetch_error_for_repo"] = repo
        log("Error getting repo", repo, ex)
        raise ex


def get_available_repos(integration):
    return integration.extras.get("repos", [])


# Various utility functions used for rendering


# TODO smart truncation dependent on total length of response - add markup and truncate accordingly
def truncate(text, length=TRUNCATE_DEFAULT):
    if not text:
        return ""
    if len(text) > length:
        return text[:length].rpartition(" ")[0] + "..."
    else:
        return text


def issue_for(comment):
    return int(comment.issue_url.split("/")[-1])


def pr_for(comment):
    return int(comment.pull_request_url.split("/")[-1])


def url_number(vals):
    return int(vals["html_url"].split("/")[-1])


def is_recent(obj, since):
    for key in "closed_at", "updated_at", "created_at":
        if not hasattr(obj, key):
            continue
        val = getattr(obj, key)
        if not val:
            continue
        return datetime.datetime.fromisoformat("%s" % val) > since
    return False


# lots of variations so do this bulletproof
def get_author_info(obj):
    name = login = None
    if hasattr(obj, "author"):
        author = obj.author
        try:
            if hasattr(author, "name"):
                name = name or author.name
            if hasattr(author, "login"):
                login = login or author.login
        except Exception:
            pass
    if hasattr(obj, "user"):
        author = obj.user
        try:
            if hasattr(author, "name"):
                name = name or author.name
            if hasattr(author, "login"):
                login = login or author.login
        except Exception:
            pass
    if hasattr(obj, "commit"):
        author = obj.commit.author
        try:
            if hasattr(author, "name"):
                name = name or author.name
            if hasattr(author, "login"):
                login = login or author.login
        except Exception:
            pass
    return (name, login)


def get_author_string(obj):
    (name, login) = get_author_info(obj)
    retval = f"{name} ({login})" if name and login and name != login else name or login
    return retval if retval else "Unknown"


# Render files and changes for a commit or a PR
def render_files_and_changes(commit, files=None):
    added = modified = deleted = additions = deletions = changes = 0
    files = files if files else commit.files
    retval = ""
    if files:
        retval = "\nFiles:"
        for idx, f in enumerate(files):
            if isinstance(f, dict):
                f = SimpleNamespace(**f)
            additions += f.additions
            deletions += f.deletions
            changes += f.changes
            if f.status == "added":
                added += 1
            elif f.status == "deleted":
                deleted += 1
            else:
                modified += 1
            if idx == MAX_FILES_TO_SHOW:
                retval += f"\n...[file list truncated]"
            if idx >= MAX_FILES_TO_SHOW:
                continue
            if f.status == "added":
                retval += f"\n{f.filename} ({f.status}, +{f.additions})"
            elif f.status == "deleted":
                retval += f"\n{f.filename} ({f.status}, -{f.deletions})"
            else:
                retval += f"\n{f.filename} (+{f.additions}, -{f.deletions})"

        retval += f"\nFile totals: ~{modified}, +{added}, -{deleted}"
    retval += f"\nLine totals: ~{changes}, +{additions}, -{deletions}"
    retval += "\n"
    return retval


def render_issue(task, issue, idx, recent):
    short_form = idx >= OPEN_ISSUE_HYDRATE_CUTOFF or (
        issue.state == "closed" and not recent and idx >= CLOSED_ISSUE_HYDRATE_CUTOFF
    )
    log("rendering issue", issue.number, issue.title, "" if short_form else "- full")
    r = "\n\n" + h4(f"Issue #{issue.number}: {issue.title}")
    struct = {
        "number": issue.number,
        "title": issue.title,
        "state": issue.state,
        "created": issue.created_at.isoformat(),
        "updated": issue.updated_at.isoformat(),
        "created_by": f"{get_author_string(issue)}",
        "comments": issue.comments,
    }

    r += "\nCreated %s" % get_days_ago(issue.created_at)
    if issue.user:
        r += f" by {get_author_string(issue)})"
    created_days = get_days_since(issue.created_at)
    edited_days = get_days_since(issue.updated_at)
    if created_days > edited_days:
        r += f"\nEdited {get_days_ago(issue.updated_at)}"
    closed_days = get_days_ago(issue.closed_at)
    if closed_days:
        struct["closed"] = issue.closed_at.isoformat()
        r += f"\nClosed {closed_days}"

    if issue.labels:
        r += "\nLabels: " + ", ".join([l.name for l in issue.labels])
        struct["labels"] = [l.name for l in issue.labels]

    if issue.milestone:
        r += f"\nMilestone: {issue.milestone.title}"
        struct["milestone"] = issue.milestone.title

    r += f"\n\n{truncate(issue.body)}\n"

    if not short_form and hasattr(issue, "get_comments"):
        issue_comments = issue.get_comments()
        if issue_comments.totalCount > 0:
            comments = issue_comments[:MAX_COMMENTS]
            r += "\nComments:\n" + "\n".join(
                [f"{get_author_string(c)}: {truncate(c.body)}" for c in comments]
            )

    task.structured_data["issues"] = task.structured_data.get("issues", []) + [struct]
    task.response += r


def structure_pr(pr, short_form=False):
    vals = {
        "number": pr.number,
        "title": "%s" % pr.title,
        "user": get_author_string(pr),
        "created_at": pr.created_at.isoformat(),
        "updated_at": pr.updated_at.isoformat(),
        "closed_at": pr.closed_at.isoformat() if pr.closed_at else None,
        "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
        "merged": "%s" % pr.merged,
        "draft": "%s" % pr.draft,
        "state": "%s" % pr.state,
        "repo": "%s" % pr.base.repo.full_name,
        "base": "%s" % pr.base.label or pr.base.ref if pr.base else None,
        "head": "%s" % pr.head.label or pr.head.ref if pr.head else None,
        "labels": [l.name for l in pr.labels],
        "milestone": pr.milestone.title if pr.milestone else None,
        "assignees": [get_author_string(a) for a in pr.assignees],
        "requested_reviewers": [get_author_string(a) for a in pr.requested_reviewers],
        "short_form": short_form,
    }
    if short_form:
        return vals
    involved = set()
    if pr.user:
        involved.add(get_author_string(pr))
    if pr.merged_by:
        involved.add(f"{pr.merged_by.name} ({pr.merged_by.login})")
        vals["merged_by"] = f"{pr.merged_by.name} ({pr.merged_by.login})"
    for comment in pr.get_review_comments():
        if comment.user:
            involved.add(get_author_string(comment.user))
    for comment in pr.get_issue_comments():
        if comment.user:
            involved.add(get_author_string(comment.user))
    for commit in pr.get_commits():
        if commit.commit.author:
            involved.add(get_author_string(commit.commit.author))
    if "Unknown" in involved:
        involved.remove("Unknown")
    vals["involved"] = list(involved)
    vals["files"] = [f.filename for f in pr.get_files()]
    return vals


def render_pr(task, pr, short_form=False, devs=None):
    # gotta limit how many we fully hydrate if there are tons of them
    suff = "" if short_form else "- full"
    log("rendering PR", pr.base.repo.full_name, pr.number, pr.title, suff)
    r = "\n" + h4(f"PR #{pr.number}: {pr.title}")
    r += f"\nRepo: {pr.base.repo.full_name}"
    r += f"\nState: {pr.state}"
    if pr.user:
        r += f"\nCreated by: {get_author_string(pr)}"

    r += "\nCreated %s" % get_days_ago(pr.created_at)
    created_days = get_days_since(pr.created_at)
    edited_days = get_days_since(pr.updated_at)
    if created_days > edited_days:
        r += f", edited {get_days_ago(pr.updated_at)}"
    closed_days = get_days_ago(pr.closed_at)
    if closed_days:
        r += f", closed {closed_days}"
        if get_days_since(pr.closed_at) > OBSOLETE_CLOSED_PR_DAYS:
            return r

    if pr.draft:
        r += f"\nDraft"
    if pr.merged_at or pr.merged:
        r += f"\nMerged"
        if pr.merged_by:
            r += f" by {pr.merged_by.name} ({pr.merged_by.login})"
        if pr.merged_at:
            r += " %s" % get_days_ago(pr.merged_at)
    elif pr.closed_at or pr.state == "closed":
        r += f"\nNot merged"

    body = pr.body or ""
    if body:
        max_length = int(task.flags.get("max_pr_body_length", MAX_PR_BODY_LENGTH))
        r += f"\n{body[:max_length]}\n"

    if pr.labels:
        r += "\nLabels: " + ", ".join([l.name for l in pr.labels])
    if pr.milestone:
        r += f"\nMilestone: {pr.milestone.title}"
    if pr.assignees:
        r += "\nAssignees: " + ", ".join([get_author_string(a) for a in pr.assignees])
    if pr.requested_reviewers:
        r += "\nRequested Reviewers: " + ", ".join(
            [get_author_string(a) for a in pr.requested_reviewers]
        )
    if short_form:
        r += "\n<!--DAI-Short-->"
        return r

    head_label = pr.head.label or pr.head.ref
    base_label = pr.base.label or pr.base.ref
    if head_label and base_label:
        if head_label.split(":")[0] == base_label.split(":")[0]:
            r += f"\nBase branch: {pr.base.ref}"
            r += f"\nHead branch: {pr.head.ref}"
        else:
            r += f"\nBase branch: {pr.base.label}"
            r += f"\nHead branch: {pr.head.label}"

    review_comments = pr.get_review_comments()
    if review_comments.totalCount > 0:
        comments = review_comments[:MAX_REVIEW_COMMENTS]
        r += "\n\nReview Comments:\n" + "\n".join(
            [f"{get_author_string(c)}: {truncate(c.body)}" for c in comments]
        )
    issue_comments = pr.get_issue_comments()
    if issue_comments.totalCount > 0:
        comments = issue_comments[:MAX_COMMENTS]
        r += "\n\nComments:\n" + "\n".join(
            [f"{get_author_string(c)}: {truncate(c.body)}" for c in comments]
        )

    commits = pr.get_commits()
    r += "\n\nCommits:"
    if commits.totalCount > 0:
        max = 9999 if devs is not None else MAX_PR_COMMITS
        for commit in commits[:max]:
            r += render_commit(commit)
            if devs is not None:
                ascribe_commit(commit, pr.base.ref, devs, task.github_metadata_only())

    files = pr.get_files()
    r += "\n" + render_files_and_changes(pr, files)

    # render diffs if small
    changes = sum([f.changes for f in files])
    if changes < 10 and not task.github_metadata_only():
        try:
            raw = get_pr_diff(task, pr)
            r += f"\nDiffs:\n{raw}\n\n"
        except Exception as ex:
            log("Could not get diffs for PR", ex)

    return r


# all GitHub PRs are issues, but not all issues are PRs
def get_gh_pulls(task, repo):
    devs = {} if task.github_metadata_only() else None
    task.structured_data = {}
    task.response = h2("Pull requests")
    task.response += h3(f"Repo: {repo.full_name}")
    days = RECENT_DAYS
    if task.is_time_series():
        previous = task.previous()
        days = get_days_between(task.created_at, previous.created_at)
        task.response += h3(f"Last analysis was {days} days ago.")
    log("Previous task", task.previous())
    log("New is considered to be %s days ago" % days)
    since = task.created_at - datetime.timedelta(days=days)

    for state in ["open", "closed"]:
        prs = repo.get_pulls(state=state)

        totalCount = prs.totalCount
        log("PR count:", totalCount, state)
        task.response += h3(f"{state.capitalize()} pull requests: {totalCount}")
        counts = task.structured_data.get("counts", {})
        counts[f"{state}_pulls"] = totalCount
        task.structured_data["counts"] = counts

        if state == "open" and totalCount > MAX_OPEN_PRS:
            prs = prs[:MAX_OPEN_PRS]
        elif state == "closed" and totalCount > MAX_CLOSED_PRS:
            prs = prs[:MAX_CLOSED_PRS]

        structs = task.structured_data.get(state, [])
        old_prs = [i for i in prs if not is_recent(i, since)]
        new_prs = [i for i in prs if is_recent(i, since)]
        log(f"{state} old {len(old_prs)} new {len(new_prs)}")

        for idx, pr in enumerate(new_prs):
            short_form = idx >= OPEN_PR_HYDRATE_CUTOFF
            task.response += render_pr(task, pr, short_form, devs=devs)
            structs += [structure_pr(pr, False)]
            task.structured_data[state] = structs
            task.save()
        task.response += "\n\n"

        for idx, pr in enumerate(old_prs):
            short_form = idx >= CLOSED_PR_HYDRATE_CUTOFF and pr.state == "closed"
            short_form = short_form or idx >= OPEN_PR_HYDRATE_CUTOFF
            task.response += render_pr(task, pr, short_form, devs=devs)
            structs += [structure_pr(pr, True)]
            task.structured_data[state] = structs
            task.save()
        task.response += "\n\n"

    total = sum(task.structured_data.get("counts", {}).values())
    if devs is not None:
        task.structured_data["devs"] = devs
    if total == 0:
        task.status = -2  # TaskStatus.EMPTY: can't import because loop
    task.save()


# all GitHub PRs are issues, but not all issues are PRs
def get_gh_issues(task, repo):
    task.response = h2("GitHub Issues")
    task.response += h3(f"Repo: {repo.full_name}")
    days = RECENT_DAYS
    if task.is_time_series():
        previous = task.previous()
        days = get_days_between(task.created_at, previous.created_at)
        task.response += h3(f"Last analysis was {days} days ago.")
    log("Previous task", task.previous())
    log("New is considered to be %s days ago" % days)
    since = task.created_at - datetime.timedelta(days=days)
    task.structured_data["issues"] = []

    for state in ["open", "closed"]:
        issues = []
        all_issues = repo.get_issues(state=state)
        total_all = all_issues.totalCount
        total_pulls = repo.get_pulls(state=state).totalCount
        totalCount = total_all - total_pulls

        max = MAX_OPEN_ISSUES if state == "open" else MAX_CLOSED_ISSUES
        for idx, issue in enumerate(all_issues):
            if issue.pull_request:
                continue
            issues.append(issue)
            if len(issues) >= max:
                break

        log("issue count:", totalCount, state)
        task.response += h3(f"{state.capitalize()} issues: {totalCount}\n")
        counts = task.structured_data.get("counts", {})
        counts[f"{state}_issues"] = totalCount
        task.structured_data["counts"] = counts

        if state == "open" and totalCount > MAX_OPEN_ISSUES:
            issues = issues[:MAX_OPEN_ISSUES]
        elif state == "closed" and totalCount > MAX_CLOSED_ISSUES:
            issues = issues[:MAX_CLOSED_ISSUES]

        old_issues = [i for i in issues if not is_recent(i, since)]
        new_issues = [i for i in issues if is_recent(i, since)]
        log(f"{state} old {len(old_issues)} new {len(new_issues)}")

        for idx, issue in enumerate(new_issues):
            render_issue(task, issue, idx, True)
        task.response += "\n\n"

        for idx, issue in enumerate(old_issues):
            render_issue(task, issue, idx, True)
        task.response += "\n\n"
        task.save()

    log("Task response length %s" % len(task.response))
    total = sum(task.structured_data.get("counts", {}).values())
    if total == 0:
        task.status = -2  # TaskStatus.EMPTY: can't import because loop
    task.save()


def get_pr_diff_by_number(task, number):
    repo = get_gh_repo(task)
    pr = repo.get_pull(number)
    return get_pr_diff(task, pr)


def get_pr_diff(task, pr):
    token = os.environ["GITHUB_TOKEN"]
    if task.get_customer() and get_source_id(task):
        auth = auth_github(task)
        auth.withRequester(get_gh_repo(task)._requester)
        token = auth.token
    url = pr.commits_url
    url = url.replace("/commits", "")
    req = requests.get(
        url,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.diff",
        },
    )
    if req.status_code != 200:
        log("Error getting diff", req.status_code, req.text)
        return ""
    else:
        return req.text


# Gets the full details, including diff, of a pull request
def get_gh_pr(task, repo, number, diffs=True):
    number = int(number) if isinstance(number, str) else number
    pr = repo.get_pull(number)
    task.response = "" if not task.response else task.response
    task.response += render_pr(task, pr)

    # Full files diff (note this will be truncated at prompt time if too long)
    # mini-hack: diffs not available via PyGitHub, get via HTTPS
    if diffs and not task.github_metadata_only():
        raw = get_pr_diff(task, pr)
        if raw:
            task.response += PR_DIFF_PROMPT % raw

    task.save()


def get_gh_pr_list(task):
    open = task.structured_data.get("open", [])
    if open:
        task.response += h2("Open Pull Requests")
        task.response += f"{len(open)} open PRs"
    for idx, pr in enumerate(open):
        repo_name = get_repo_name_from_url(pr["data_task_url"])
        repo = get_gh_repo(task, repo_name)
        try:
            get_gh_pr(task, repo, pr["number"], diffs=False)
        except Exception as ex:
            log("Failed fetch open PR", pr["number"], pr["data_task_url"], idx, ex)

    closed = task.structured_data.get("closed", [])
    if closed:
        task.response += h2("Closed Pull Requests")
        task.response += f"{len(closed)} open PRs"
    for idx, pr in enumerate(closed):
        repo_name = get_repo_name_from_url(pr["data_task_url"])
        repo = get_gh_repo(task, repo_name)
        try:
            get_gh_pr(task, repo, pr["number"], diffs=False)
        except Exception as ex:
            log("Failed fetch closed PR", pr["number"], pr["data_task_url"], idx, ex)


def get_gh_actions(task, repo):
    structured = {}
    flows = {}
    workflows = repo.get_workflows()
    r = h2("GitHub Actions")
    r += h3(f"Repo: {repo.full_name}")
    r += f"Total workflows: {workflows.totalCount}\n"
    structured["workflows"] = workflows.totalCount
    for workflow in workflows:
        flows[workflow.id] = workflow.name
        r += h4(f"Workflow: {workflow.name}")
        # r += f"ID: {workflow.id}\n"
        r += f"Created at: {workflow.created_at}\n"
        r += f"Updated at: {workflow.updated_at}\n"
        r += f"State: {workflow.state}\n"

    cutoff_date = timezone.now() - datetime.timedelta(days=task.commit_days())
    cutoff = datetime.datetime.strftime(cutoff_date, "%Y-%m-%d")
    runs = repo.get_workflow_runs(created=">=" + cutoff)
    structured["runs"] = runs.totalCount
    for run in runs:
        r += h4(f"Workflow Run: {run.name}")
        r += f"\nTitle: {run.display_title}"
        r += f"\nHead branch: {run.head_branch}"
        r += f"\nStatus: {run.status}"
        r += f"\nEvent: {run.event}"
        r += f"\nConclusion: {run.conclusion}"
        r += f"\nCreated at: {run.created_at}"
        r += f"\nUpdated at: {run.updated_at}"
        vals = {
            "workflow": run.workflow_id,
            "title": run.display_title,
            "created": run.created_at.isoformat(),
            "event": run.event,
            "branch": run.head_branch,
            "status": run.status,
            "conclusion": run.conclusion,
        }
        flow = structured.get(run.workflow_id, {})
        flow["runs"] = flow.get("runs", []) + [vals]
        flow["name"] = flows.get(run.workflow_id) or run.display_title
        structured[run.workflow_id] = flow

    task.structured_data = structured
    task.response = r


# Used by the README fetch method below
def add_field(task, key, val):
    task.structured_data[key] = val or ""
    if not val:
        return ""
    keylabel = key.capitalize().replace("_", " ")
    if key == "repo":
        return h3(f"{keylabel}: [{val}](https://github.com/{val})")
    elif key == "size":
        return f"\n{keylabel} (kB): {val}"
    elif key == "stargazers_count":
        return f"\nStars: {val}"
    elif key == "open_issues_count":
        return f"\nTotal open issues and pull requests: {val}"
    elif key == "archived" and (val == "True" or val == True):
        return f"\n**This repo has been archived**"
    else:
        return f"\n{keylabel}: {val}"


def get_gh_readme(task, repo):
    r = add_field(task, "repo", repo.full_name)
    r += add_field(task, "created_at", repo.created_at.isoformat())
    r += add_field(task, "pushed_at", repo.pushed_at.isoformat())
    r += add_field(task, "size", repo.size)
    r += add_field(task, "forks", repo.forks)
    r += add_field(task, "open_issues_count", repo.open_issues_count)
    r += add_field(task, "total_commits", repo.get_commits().totalCount)
    r += add_field(task, "default_branch", repo.default_branch)
    r += add_field(task, "total_branches", repo.get_branches().totalCount)
    r += add_field(task, "homepage", repo.homepage)
    r += add_field(task, "language", repo.language)
    r += add_field(task, "archived", repo.archived)
    if repo.private:
        r += "\nThis repo is private"
    else:
        r += add_field(task, "watchers", repo.subscribers_count)
        r += add_field(task, "stargazers_count", repo.stargazers_count)
        if repo.license:
            r += add_field(task, "license", repo.license.name)
    if repo.organization:
        r += add_field(task, "organization", repo.organization.login)
    r += add_field(task, "description", repo.description)
    task.response = r
    task.save()

    readme = "Unable to access README"
    readme_b64 = repo.get_readme().content
    readme_enc = base64.b64decode(readme_b64)
    readme = "%s" % readme_enc.decode("utf-8", errors="replace").replace(
        "\x00", "\uFFFD"
    )
    task.response += h2("README") + readme

    r = h2("Repo files (name, size in bytes)")
    main = repo.get_branch(repo.default_branch)
    tree = repo.get_git_tree(main.commit.sha, recursive=True)
    paths = get_tree_paths(tree)
    r += "\n".join([f"{p[0]} {p[1]}" for p in paths])
    task.response += r


# limit to 512 files by default
def get_tree_paths(tree, max_files=512):
    paths = []
    stack = [tree]
    lines = 0
    exclusions = EXCLUDE_FROM_TREE
    while stack and lines < max_files:
        current = stack.pop()
        for t in current.tree:
            if hasattr(t, "tree"):
                stack.append(t.tree)  # Push the nested tree onto the stack
            elif t.path:
                exclude = False
                for e in exclusions:
                    if e in t.path or t.path.endswith(e) or not t.size:
                        exclude = True
                        break
                if not exclude:
                    paths.append((t.path, t.size))
                    lines += 1
            if lines >= max_files:
                break
    return paths


def render_commit(commit):
    author = get_author_string(commit)
    message = (
        (commit.commit.message or "")
        .strip()
        .replace("\r\n", "\n")
        .replace("\n\n", "\n")
    )
    daystring = get_days_ago(commit.commit.author.date)
    delim = "\n" if "\n" in message else " "
    return f"\n{daystring} - {message}{delim}by {author}"


def ascribe_commit(commit, branch, devs, metadata_only=False):
    (name, login) = get_author_info(commit)
    key = login if name and login else login or name
    devdata = devs.get(key, {})
    if name and not "name" in devdata:
        devdata["name"] = name
        devdata["login"] = login
        devdata["link"] = f"[{name}](https://github.com/{key})"
        devdata["avatar"] = "<img src='https://github.com/%s.png?size=50'>" % key

    commits = devdata.get("commits", [])
    days_ago = get_days_since(commit.commit.author.date)
    # log("Ascribing commit", commit.sha, "branch", branch, "days_ago", days_ago)
    commit_data = {
        "sha": commit.sha,
        "days_ago": days_ago,
        "branch": branch,
        "changes": 0 if metadata_only else commit.stats.total,
        "files": [] if metadata_only else [f.filename for f in commit.files],
        "type": "merge" if commit.parents and len(commit.parents) > 1 else "normal",
    }
    commits.append(commit_data)
    devdata["commits"] = commits
    devs[key] = devdata


# This gets messy because we are doing both qualitative and quantitave analysis
# For quantitave analysis, we sometimes want a fixed window of commits
# For qualitative analysis, we want N recent commits, but probably only want to
# fully hydrated the most recent - the unhydrated are still good context though
# As such, we calculate a "max_days" for qualitative hydration,
def is_significant_date(task, date):
    if not date:
        return False
    if task.is_fixed_window():
        # we're only fetching commits we want to quantify
        return task.window_start() <= date and date <= task.window_end()
    # always get everything more recent than the previous task if in time series
    if task.previous() and task.previous().completed_at:
        if date > task.previous().completed_at:
            return True
    max_days = task.commit_days()
    min_days = task.flags.get("min_days") or 0
    days = get_days_since(date)
    return days >= min_days and days <= max_days


def is_significant_commit(task, commit):
    return is_significant_date(task, commit.commit.author.date)


def is_significant_pr(task, pr):
    return (
        is_significant_date(task, pr.created_at)
        or is_significant_date(task, pr.closed_at)
        or is_significant_date(task, pr.merged_at)
    )


def get_gh_commits(task, repo):
    devs = {}
    time_series = task.is_time_series()
    max_days = task.commit_days()
    since = until = None
    if task.is_fixed_window():
        since = task.window_start()
        until = task.window_end()
        commits = repo.get_commits(since=since, until=until)
        log("Getting commits, fixed window", since, until)
    else:
        max_commits = task.flags.get("max_commits", MAX_COMMITS)
        commits = repo.get_commits()[:max_commits]
        log("Getting commits, hydrating max_days", max_days)
    commits = [c for c in commits]
    main_shas = [c.sha for c in commits]
    parsed_shas = []
    if task.parent:
        parsed_shas = task.parent.structured_data.get("parsed_shas", [])

    # first off, main commits
    r = h2("Recent commits")
    r += h3(f"Repo: {repo.full_name}")
    if task.is_time_series():
        previous = task.previous()
        days = get_days_between(task.created_at, previous.created_at)
        r += h3(f"Last analysis was {days} days ago.")

    # Edge case: if the main branch is ancient and we render it before more recent dev branches,
    # the LLM gets confused, so only render it if relatively recent
    main_days = get_days_since(commits[0].commit.author.date) if commits else 10000
    main_text = h4("Commits in default branch: %s" % repo.default_branch)

    hydrated = 0
    idx = 0
    for commit in commits:
        if commit.sha in parsed_shas:
            log("Already parsed", commit.sha)
            continue
        days = get_days_since(commit.commit.author.date)
        main_text += render_commit(commit)
        parsed_shas.append(commit.sha)
        if idx > hydrated and idx % 10 == 0:
            log("rendering commit", commit.sha, "days", days, "iter", idx)
        # attribute 7 most recent days' worth of commits for quantitative dev data
        if is_significant_commit(task, commit):
            ascribe_commit(commit, repo.default_branch, devs)
            if hydrated < COMMIT_HYDRATE_CUTOFF:
                if not time_series or days <= max_days:
                    log("hydrating commit", commit.sha, "days", days, "iter", idx)
                    main_text += render_files_and_changes(commit)
                    hydrated += 1
        idx += 1

    # non-edge case of recent main branch
    if main_days < COMMIT_INTEREST_CUTOFF:
        r += main_text
        main_text = ""

    task.response = r
    task.save()

    # getting the actual active branches is weirdly a pain, surely there's a better way?
    branches = repo.get_branches()
    log("Rendering branch commits, total branches", branches.totalCount)
    r += "\n\n" + h3("Total branches: %s" % branches.totalCount)
    active_branches = [b for b in branches if b.commit.sha not in main_shas]
    active_branches = [b for b in branches if b.commit.sha not in parsed_shas]
    active_branches = active_branches[:MAX_BRANCHES_TO_CONSIDER]
    log("Active branches", len(active_branches))

    # now get PRs and update dev data accordingly
    prs = repo.get_pulls(state="all")
    total_prs = prs.totalCount
    log("Total PRs", total_prs)
    prs = prs[:MAX_PRS] if total_prs > MAX_PRS else prs
    all_pr_branches = set()
    for pr in prs:
        if not is_significant_pr(task, pr):
            continue
        login = pr.user.login
        dev = devs.get(login, {})
        if not dev:
            name = pr.user.name
            dev = {"name": name, "login": login, "link": f"{name} ({login})"}
            log("PR creator added to devs", login, name)

        pr_branches = set(dev.get("pr_branches", []))
        branch_label = pr.head.ref or pr.head.label
        if "%s:" % repo.name in branch_label:
            branch_label = branch_label.split(":")[1]
        if is_significant_date(task, pr.created_at):
            dev["prs_opened"] = dev.get("prs_opened", 0) + 1
            pr_branches.add(branch_label)
        if is_significant_date(task, pr.merged_at):
            dev["prs_merged"] = dev.get("prs_merged", 0) + 1
            pr_branches.add(branch_label)
        elif is_significant_date(task, pr.closed_at):
            dev["prs_closed"] = dev.get("prs_closed", 0) + 1
            pr_branches.add(branch_label)
        dev["pr_branches"] = list(pr_branches)
        all_pr_branches.update(pr_branches)
        devs[login] = dev

    done_shas = [b.commit.sha for b in active_branches] + main_shas + parsed_shas
    for branch_label in all_pr_branches:
        try:
            branch = repo.get_branch(branch_label)
            if not branch.commit.sha in done_shas:
                active_branches.append(branch)
        except Exception as ex:
            log("Failed to get branch", branch_label, ex)

    recent_branches = []
    for branch in active_branches:
        commit = repo.get_commit(branch.commit.sha)
        branch.last_active = commit.commit.author.date
        if get_days_since(branch.last_active) < BRANCH_HYDRATE_DAYS:
            recent_branches.append(branch)
    recent_branches.sort(key=lambda x: x.last_active, reverse=True)
    log("Recent branches", len(recent_branches))
    recent_branches = recent_branches[:MAX_BRANCHES]
    if len(recent_branches) > 0:
        log("Latest recent branch", recent_branches[0].last_active)
        log("Furthest recent branch", recent_branches[-1].last_active)

    # OK, we finally have the relevant branches, parse the commits
    r += h3("Recently active branches: %s" % len(recent_branches))
    for branch in recent_branches:
        log("Considering branch", branch.name)
        if task.is_fixed_window():
            branch_commits = repo.get_commits(
                branch.commit.sha, since=since, until=until
            )
        else:
            cutoff = timezone.now() - datetime.timedelta(days=BRANCH_HYDRATE_DAYS)
            branch_commits = repo.get_commits(branch.commit.sha, since=cutoff)
            branch_commits = branch_commits[:MAX_BRANCH_COMMITS]

        branch_commits = [c for c in branch_commits if c.sha not in main_shas]
        branch_commits = [c for c in branch_commits if c.sha not in parsed_shas]

        if branch_commits:
            branch_text = "\n" + h4("Commits in branch: %s" % branch.name)
            for branch_commit in branch_commits:
                branch_days = get_days_since(branch_commit.commit.author.date)
                branch_text += render_commit(branch_commit)
                parsed_shas.append(branch_commit.sha)
                if is_significant_commit(task, branch_commit):
                    ascribe_commit(branch_commit, branch.name, devs)
                    if not time_series or days <= max_days:
                        log("hydrating branch commit", branch_commit.sha)
                        branch_text += render_files_and_changes(branch_commit)

                # edge case of ancient main branch
                if main_text and main_days - branch_days < BRANCH_HYDRATE_DAYS:
                    r += main_text
                    main_text = ""

            r += branch_text

    r += main_text if main_text else ""
    task.structured_data["parsed_shas"] = parsed_shas
    task.structured_data["devs"] = devs
    task.response = r
    task.save()

    if devs:
        r += "\n\n" + h3(f"Developer commit activity within {max_days} days")
        for name in devs:
            dev = get_dev_summary(devs[name])
            r += h4(name)
            r += f"{dev.commits} commits with {dev.changes} changes across {dev.files} files and {dev.branches} branches.\n"
            r += f"\nPRs: {dev.prs} open / merged / closed-unmerged across {dev.pr_branches} branches\n"

    task.structured_data["devs"] = devs
    task.response = r
    task.save()


def get_gh_file(repo, finfo, retry=0):
    url = finfo.get("url", finfo.get("path", finfo.get("name")))
    if retry == 1 or retry == 3:
        url = finfo.get("name")
    if not url.startswith("http") and not url.startswith("/"):
        url = "/" + url
    if retry == 2 or retry == 3:
        url = repo.full_name.split("/")[-1] + url
    path = url.replace(GITHUB_PREFIX, "/")
    if path.startswith(f"/{repo.full_name}"):
        path = path.replace(f"/{repo.full_name}", "")
    try:
        content = repo.get_contents(path).content
        # log("Content fetched", path)
        return base64.b64decode(content).decode("utf-8")
    except Exception:
        if retry < 3:
            return get_gh_file(repo, finfo, retry + 1)


def get_repo_avatar(repo):
    url = ""
    cache_key = "gh_avatar_%s" % repo
    if cache.get(cache_key):
        return cache.get(cache_key)
    try:
        token = os.environ["GITHUB_TOKEN"]
        auth = github.Auth.Token(token)
        gh = github.Github(
            auth=auth, user_agent="PyGitHub/Python|YamLLMs|info@" + settings.BASE_DOMAIN
        )
        repo = gh.get_repo(repo)
        url = (
            repo.organization.avatar_url if repo.organization else repo.owner.avatar_url
        )
    except Exception as ex:
        log("Error getting repo avatar", url)
    cache.set(cache_key, url, 60 * 60 * 24)
    return url
