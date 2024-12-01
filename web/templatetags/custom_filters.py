from django import template
import json
from django.utils.safestring import mark_safe
import markdown

register = template.Library()


@register.filter
def get_first_repo(value):
    try:
        # If it's already a list, return the first item
        if isinstance(value, list):
            return value[0] if value else ""
        # If it's a string, try to parse as JSON
        if isinstance(value, str):
            repos = json.loads(value)
            if isinstance(repos, list):
                return repos[0] if repos else ""
            return repos  # If it's a single string
        return value  # If it's neither a list nor a string, return as is
    except json.JSONDecodeError:
        # If it's not valid JSON, return as is
        return value


@register.filter
def has_category(sub_reports, category):
    return any(report.get_category_display() == category for report in sub_reports)


@register.filter
def has_non_category(sub_reports, category):
    return any(report.get_category_display() != category for report in sub_reports)


@register.filter(name="custom_markdown")
def custom_markdown(value, task):
    if task.flags.get("skip_markdown"):
        return mark_safe(value)
    return mark_safe(markdown.markdown(value))
