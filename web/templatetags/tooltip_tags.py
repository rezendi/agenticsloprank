from django import template
from django.utils.safestring import mark_safe

register = template.Library()

@register.simple_tag
def tooltip(text):
    return mark_safe(f'<span class="tooltip-icon"><span class="tooltip-text">{text}</span></span>')