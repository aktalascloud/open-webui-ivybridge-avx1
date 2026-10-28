"""Private provider configuration without reading or modifying the host environment."""
_values={}

def configure(values):
    _values.clear();_values.update({str(key):str(value) for key,value in values.items()})

def get(name,default=None):return _values.get(name,default)
