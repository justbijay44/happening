from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):

    return dictionary.get(str(key))

@register.filter
def is_integer(value):
    return isinstance(value, int)