"""Function policy and schemas. No HTTP, stream, account or SDK dependency."""
from copy import deepcopy
import json
import re

from jsonschema import Draft202012Validator, SchemaError
from referencing import Registry

from .responses_errors import ResponseError


def json_arguments(value):
    def invalid(_): raise ValueError('Non-finite number')
    return json.loads(value, parse_constant=invalid)


def _pointer(root, ref):
    if not isinstance(ref,str) or not ref.startswith('#/'):
        raise ResponseError('Only local JSON Pointer references are supported', param='tools')
    target = root
    try:
        for segment in ref[2:].split('/'):
            if re.search(r'~(?![01])',segment): raise ValueError()
            segment = segment.replace('~1','/').replace('~0','~')
            if isinstance(target,list):
                if not segment.isdecimal(): raise ValueError()
                target = target[int(segment)]
            else: target = target[segment]
        if not isinstance(target,(dict,bool)): raise ValueError()
    except (ValueError,KeyError,TypeError,IndexError):
        raise ResponseError('Invalid local schema reference',param='tools') from None
    return target


def _nodes(schema, depth=0, *, root=None, seen=None):
    if depth > 64: raise ResponseError('Function schema is too deeply nested', param='tools')
    if not isinstance(schema, dict): return
    if root is None: root = schema
    if seen is None: seen = set()
    if id(schema) in seen: return
    seen.add(id(schema))
    yield schema
    if '$ref' in schema:
        yield from _nodes(_pointer(root,schema['$ref']),depth+1,root=root,seen=seen)
    for key in ('properties', '$defs', 'definitions', 'patternProperties', 'dependentSchemas'):
        for value in schema.get(key, {}).values(): yield from _nodes(value,depth+1,root=root,seen=seen)
    for key in ('items', 'additionalProperties', 'contains', 'not', 'if', 'then', 'else',
                'propertyNames', 'unevaluatedProperties', 'unevaluatedItems'):
        value = schema.get(key)
        if isinstance(value, dict): yield from _nodes(value,depth+1,root=root,seen=seen)
    for key in ('anyOf', 'oneOf', 'allOf', 'prefixItems'):
        for value in schema.get(key, []): yield from _nodes(value,depth+1,root=root,seen=seen)


def _check_schema(schema, param):
    try:
        if len(json.dumps(schema, allow_nan=False).encode()) > 262144:
            raise ResponseError('Function schema is too large', 413, param=param)
        Draft202012Validator.check_schema(schema)
        for node in _nodes(schema):
            Draft202012Validator.check_schema(node)
            # Resource scopes/dynamic resolution would change root pointer meaning.
            if any(k in node for k in ('$id', '$anchor', '$dynamicAnchor', '$dynamicRef')):
                raise ResponseError('Schema resource scopes and dynamic references are unsupported', param=param)
    except ResponseError as error:
        error.param = param
        raise
    except (SchemaError, ValueError, KeyError, IndexError, TypeError, RecursionError):
        raise ResponseError('Invalid function parameter schema or reference', param=param) from None


def _strict(schema, normalize):
    if not isinstance(schema, dict) or not (schema.get('type') == 'object' or '$ref' in schema):
        return False
    for node in _nodes(schema):
        if any(k in node for k in ('allOf','oneOf','if','then','else','not','patternProperties',
                'dependentSchemas','dependentRequired','propertyNames','unevaluatedProperties',
                'unevaluatedItems','prefixItems','contains')):
            return False
        kind = node.get('type')
        if kind == 'object' or isinstance(kind, list) and 'object' in kind:
            properties = node.get('properties', {})
            if normalize:
                node['properties'] = properties
                node['required'] = list(properties)
                node['additionalProperties'] = False
            elif node.get('additionalProperties') is not False or set(node.get('required', [])) != set(properties):
                return False
        elif 'properties' in node or 'additionalProperties' in node:
            return False
    return True


def normalize_tools(tools):
    if len(tools) > 64: raise ResponseError('Too many function tools', param='tools')
    result, names = [], set()
    for index, original in enumerate(tools):
        param = f'tools[{index}]'
        tool = dict(original)
        name = tool.get('name')
        if (tool.get('type') != 'function' or not isinstance(name, str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name)):
            raise ResponseError('Only named function tools are supported', param=param)
        if name in names: raise ResponseError('Duplicate function name', param=param + '.name')
        names.add(name)
        if set(tool) - {'type','name','description','parameters','strict'}:
            raise ResponseError('Unsupported function tool field', param=param)
        strict = tool.get('strict')
        if strict is not None and not isinstance(strict, bool):
            raise ResponseError('strict must be boolean or null', param=param + '.strict')
        if 'description' in tool and not isinstance(tool['description'], str):
            raise ResponseError('description must be a string', param=param + '.description')
        schema = tool.get('parameters')
        if schema is None: schema = {'type':'object','properties':{},'required':[],'additionalProperties':False}
        if not isinstance(schema, dict): raise ResponseError('parameters must be an object', param=param + '.parameters')
        _check_schema(schema, param + '.parameters')
        try: effective = deepcopy(schema)
        except RecursionError:
            raise ResponseError('Function schema is too deeply nested',param=param+'.parameters') from None
        if strict is True:
            if not _strict(effective, False): raise ResponseError('Unsupported or non-strict function schema', param=param + '.parameters')
        elif strict is None:
            strict = _strict(effective, True)
            if not strict: effective = schema
        tool.update(parameters=effective, strict=bool(strict))
        result.append(tool)
    return result


def validate_choice(tools, choice):
    names = {t['name'] for t in tools}
    if isinstance(choice, str):
        if choice not in ('auto','none','required') or choice == 'required' and not tools:
            raise ResponseError('Invalid tool choice', param='tool_choice')
    elif (not isinstance(choice, dict) or set(choice) != {'type','name'}
          or choice.get('type') != 'function' or not isinstance(choice.get('name'), str)
          or choice['name'] not in names):
        raise ResponseError('tool_choice must name an available function', param='tool_choice')


def validate_call_batch(tools, choice, calls, *, parallel, complete=True):
    if len(calls) > (64 if parallel else 1): raise ResponseError('Upstream exceeded function call limit', 502)
    if complete and not calls and (choice == 'required' or isinstance(choice, dict)):
        raise ResponseError('Upstream did not call the required function', 502)
    by_name, seen = {t['name']:t for t in tools}, set()
    for call in calls:
        try:
            call_id, fn = call['id'], call['function']
            if not isinstance(call_id, str) or not call_id or call_id in seen: raise ValueError()
            seen.add(call_id)
            name = fn['name']
            if not isinstance(name, str) or name not in by_name or choice == 'none': raise ValueError()
            if isinstance(choice, dict) and choice['name'] != name: raise ValueError()
            args = json_arguments(fn['arguments'])
            if by_name[name].get('strict'):
                Draft202012Validator(by_name[name]['parameters'], registry=Registry()).validate(args)
        except Exception:
            raise ResponseError('Upstream function call failed validation', 502) from None


def pending_calls(messages):
    known, pending, resolved = {}, {}, set()
    for index, message in enumerate(messages):
        for call in message.get('tool_calls', []):
            call_id = call.get('id')
            if not isinstance(call_id, str) or not call_id or call_id in known:
                raise ResponseError('Invalid or duplicate call_id', param=f'input[{index}].call_id')
            known[call_id] = pending[call_id] = call['function']['name']
        if message.get('role') == 'tool':
            call_id = message.get('tool_call_id')
            if not isinstance(call_id, str) or call_id not in pending or call_id in resolved:
                raise ResponseError('Unknown or duplicate function output', param=f'input[{index}].call_id')
            pending.pop(call_id); resolved.add(call_id)
    return pending
