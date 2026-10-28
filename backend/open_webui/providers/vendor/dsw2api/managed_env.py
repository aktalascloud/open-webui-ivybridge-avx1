"""Private provider configuration without reading or modifying the host environment."""
from contextvars import ContextVar
_values={}
request_thinking=ContextVar('owui_deepseek_request_thinking',default=True)

def configure(values):
    _values.clear();_values.update({str(key):str(value) for key,value in values.items()})

def get(name,default=None):return _values.get(name,default)
