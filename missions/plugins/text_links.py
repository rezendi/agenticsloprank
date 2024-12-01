import re
from ..util import *


def process_text(obj, text=None):
    if obj.flags.get("no_post_process") == "true":
        return text
    processed = text if text else obj.response or ""
    # this is of the form {"13": "abcd/efgh", "1234: "ijkl/mnop"} for multiple repos
    # to map PR/issue numbers to repos, or simply {}"repo":"abcd/efgh" for a single repo}
    # for now, we only link files for single repos
    repos = obj.get_repos()
    if repos:
        processed = link_entities(processed, repos)
    default_repo = list(repos.values())[0] if len(repos) == 1 else ""
    if default_repo:
        processed = link_files(processed, default_repo, obj.default_git_branch())
    processed = link_arxiv(processed)
    processed = fix_markdown_lists(processed)
    jira = obj.get_integration("jira")
    if jira:
        jira_projects = get_jira_projects_from(jira)
        url = get_jira_url_from(jira)
        if url:
            processed = link_jira(processed, url, jira_projects)
    return processed


def link_entities(text, repos):
    default_repo = list(repos.values())[0] if len(repos) == 1 else ""
    in_words = text.split("#")
    out_words = [in_words[0]]
    for i, word in enumerate(in_words):
        if i == 0:
            continue
        pre = in_words[i - 1]
        if (
            pre.endswith("[")
            or pre.endswith("/")
            or pre.endswith("[PR ")
            or pre.endswith("[Issue ")
            or "href=" in pre
        ):
            out_words.append(f"#{word}")
            continue
        int_idx = next((i for i, v in enumerate(word) if not v.isnumeric()), -1)
        if int_idx <= 0:
            out_words.append(f"#{word}")
            continue
        if int_idx < len(word) and word[int_idx] == ".":
            if len(word) > int_idx + 1 and word[int_idx + 1].isnumeric():
                out_words.append(f"#{word}")
                continue
        # TODO: don't link if we're inside a code block / backticks
        try:
            num = int(word[:int_idx])
            repo_to_link = "%s" % (repos.get(num) or default_repo or "").strip()
            if repo_to_link:
                markdown = f"[#{num}]({GITHUB_PREFIX + repo_to_link}/issues/{num})"
                out_words.append(markdown + word[int_idx:])
            else:
                out_words.append(f"#{word}")
        except Exception as ex:
            log("Could not link to", word[:int_idx])
    linked_text = "".join(out_words)

    # sometimes the LLM itself wrongly uses /pulls/ in the path
    linked_text = re.sub(r"(/pulls/)(\d+\))", "/issues/\g<2>", linked_text)

    return linked_text


def link_arxiv(text):
    # link arxiv numbers
    arxiv_link = r"[\1](https://arxiv.org/abs/\1)"
    linked_text = re.sub(r"\[(\d{4}\.\d{5})\]^\(", arxiv_link, text)
    linked_text = re.sub(r"(?<!\[)#(\d{4}\.\d{5})", arxiv_link, linked_text)
    return linked_text


def fix_markdown_lists(text):
    # fix nested markdown lists
    linked_text = text.replace("\r\n", "\n")
    linked_text = linked_text.replace("\n  -", "\n    -")
    linked_text = linked_text.replace("\n   -", "\n    -")
    linked_text = linked_text.replace("*\n-", "*\n\n-")
    linked_text = linked_text.replace(":\n-", ":\n\n-")
    return linked_text


def link_files(text, repo, default_branch):
    if not default_branch:  # we can't really link, so
        return text

    replace = []
    dirs = [m.start() for m in re.finditer("` directory", text)]
    for dir in dirs:
        start = text.rfind("`", 0, dir)
        name = text[start + 1 : dir]
        if not any(s in name for s in (" ", "\n", "\r", "\t")) and len(name) < 64:
            md = f"[`{name}`]({GITHUB_PREFIX}{repo}/tree/{default_branch}/{name})"
            replace += [(start, dir + 1, md)]

    files = [m.start() for m in re.finditer(".[a-z]{1,5}`", text)]
    for file in files:
        start = text.rfind("`", 0, file)
        end = text.find("`", file)
        name = text[start + 1 : end]
        suffix = "." + name.split(".")[-1]
        if suffix in LINK_SUFFIXES and len(name) < 64:
            if end < len(text) + 2 and text[end + 1 : end + 3] == "](":
                log("already linked")
                continue  # already linked
            md = f"[`{name}`]({GITHUB_PREFIX}{repo}/blob/{default_branch}/{name})"
            replace += [(start, end + 1, md)]

    replace = sorted(replace, key=lambda x: x[0])
    linked_text = ""
    latest = 0
    for r in replace:
        linked_text = linked_text + text[latest : r[0]] + r[2]
        latest = r[1]
    linked_text += text[latest:]
    return linked_text


def link_jira(text, url, jira_projects):
    jira_link = f"[\g<0>]({url}/browse/\g<0>)"
    if jira_projects:
        linked_text = text
        for project in jira_projects:
            # exclude when starting with backticks because they're often branches, where branches double as JIRA ticket keys
            # exclude '>' since this is probably the end of the opening of a link tag
            linked_text = re.sub(
                r"(?<![\/`>])\b{0}+-[1-9][0-9]*".format(project), jira_link, text
            )
    else:
        linked_text = re.sub(r"(?<!`)\b[A-Z][A-Z0-9_]+-[1-9][0-9]*", jira_link, text)

    return linked_text


def fix_titles(task):
    if task.flags.get("task_title") and task.is_prompted():
        title = "## %s" % task.flags["task_title"]
        if not (task.response or "").startswith(title):
            r = "\n" + task.response
            r = r.replace("\n### ", "\n##### ")
            r = r.replace("\n## ", "\n#### ")
            r = r.replace("\n# ", "\n### ")
            task.response = title + r


# this is pretty hacky
def link_to_leaf_reports(task, missions):
    customer = task.get_customer()
    if not customer:
        return  # no projects, no links
    projects = customer.project_set.all()
    if not projects:
        return  # no projects, no links

    links = {}
    log("linking to leaf reports for missions", missions)
    for project in projects:
        for mission in missions:
            name = project.name
            for word in customer.name.split():
                name = name.replace(word, "")
            if name.strip() in mission.name and not project.name in links:
                links[project.name] = BASE_PREFIX + "/reports/%s" % mission.id

    # OK now do the actual replacing
    task.response = task.response.replace("\r\n", "\n")
    paras_in = task.response.split("\n\n")
    paras_out = []
    names = list(links.keys()).copy()
    for para in paras_in:
        for name in names:
            if name in links and name in para[:160] and not links[name] in para[:240]:
                para = para.replace(name, f"[{name}]({links[name]})", 1)
                links.pop(name)
        paras_out.append(para)
    task.response = "\n\n".join(paras_out)
    task.save()
