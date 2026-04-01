from django import template

from sales.translation_catalog import translate_ui_text

register = template.Library()


@register.simple_tag
def ui(text):
    return translate_ui_text(text)


@register.filter(name='ui')
def ui_filter(text):
    return translate_ui_text(text)
