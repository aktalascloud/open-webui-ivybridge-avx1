"""Run real OWUI parameter conversion; optional pinned Strata parser, no model calls."""
import argparse
import ast
import collections.abc
import copy
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Callable
import types
import runpy
import sys

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--strata-source',type=Path)
parser.add_argument('--node',default='node')
parser.add_argument('--template',type=Path)
parser.add_argument('--receipt',type=Path)
args=parser.parse_args()

def functions(path,names,namespace):
    tree=ast.parse(path.read_text('utf-8'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes}!=set(names):raise RuntimeError('Actual parameter functions changed')
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),namespace)
    return tree

namespace={'Callable':Callable,'collections':collections,'JSONCodec':json,
           'log':types.SimpleNamespace(exception=lambda *a:None)}
functions(ROOT/'backend/open_webui/utils/misc.py',['deep_update'],namespace)
functions(ROOT/'backend/open_webui/utils/payload.py',
          ['apply_params_to_form_data','apply_model_params_to_body','remove_open_webui_params','apply_model_params_to_body_openai'],namespace)
script="""import {applyStrataReasoning} from './src/lib/utils/strataReasoning.js';
const model={id:'strata.fixture',info:{meta:{strata_reasoning_profile:'davidau'}}};
console.log(JSON.stringify(['none','low','medium','high','xhigh','ultra'].map(level=>({level,
params:applyStrataReasoning({temperature:.7,custom_params:{min_p:.05}},model,{[model.id]:level})}))));"""
vectors=json.loads(subprocess.check_output([args.node,'--input-type=module','-e',script],cwd=ROOT,text=True))
package=types.ModuleType('strata_reasoning_fixture')
package.__path__=[str(ROOT/'backend/open_webui/utils')]
sys.modules[package.__name__]=package
module=runpy.run_path(str(ROOT/'backend/open_webui/utils/strata_reasoning.py'),run_name='strata_reasoning_fixture.strata_reasoning')
adapter=module['apply_strata_reasoning_profile']
picker=module['adaptive_reasoning_mode']
supported=['coder','comedy','vader','spoon','ultra','curie','teacher','off','low','medium','xhigh']
adaptive_vectors=[]
for text,expected in [('fix the python bug and refactor the parser module','coder'),
                      ('tell me a funny joke about my job','comedy'),
                      ('we must decide whether to commit to the acquisition','vader'),
                      ('research the sources and cite the papers','spoon'),
                      ('исправь ошибку в Python и доработай парсер','coder'),
                      ('исследуй источники и процитируй научные статьи','spoon'),
                      ('flurb the wibbit qzpzz',None),('',None)]:
    assert picker(text,supported)==expected,(text,picker(text,supported),expected)
    source={'_strata_reasoning_mode':'adaptive','messages':[{'role':'user','content':text}]}
    result=adapter(source,True,supported_modes=supported)
    adaptive_vectors.append((source,result,expected))
    if expected:assert result['messages'][0]['content']=='{REASON:'+expected+'}\n'+text
    else:assert result['messages']==source['messages']
assert picker('fix the python bug and refactor the parser module',[]) is None
strata=None
template=None
proof=[]
if args.template:
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    env=ImmutableSandboxedEnvironment(trim_blocks=True,lstrip_blocks=True,extensions=['jinja2.ext.loopcontrols'])
    env.filters['tojson']=lambda value,**kwargs:json.dumps(value,ensure_ascii=kwargs.pop('ensure_ascii',False),**kwargs)
    env.filters['from_json']=json.loads
    def invalid(value):raise ValueError(value)
    env.globals['raise_exception']=invalid
    template=env.from_string(args.template.read_text('utf-8'))
if args.strata_source:
    strata={'ENV_TO_USER':False,'_NUMERIC_EFFORT':False,'_BINARY_THINKING':False}
    tree=functions(args.strata_source,['effort_kwargs','_object_list','_tool_list','_env_to_user','_late_system_to_user','openai_to_messages'],strata)
    strata['EFFORT']=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='EFFORT' for t in n.targets)))
for vector in vectors:
    level=vector['level'];params=vector['params']
    transport='xhigh' if level=='ultra' else level
    for converter in ['apply_params_to_form_data','apply_model_params_to_body_openai']:
        body={'model':'fixture','messages':[]}
        if converter=='apply_params_to_form_data':
            body['params']=copy.deepcopy(params)
            out=namespace[converter](body,{'owned_by':'openai'})
        else:out=namespace[converter](copy.deepcopy(params),body)
        assert out['reasoning_effort']==transport
        assert out['chat_template_kwargs']['enable_thinking']==(level!='none')
        assert out['temperature']==.7 and out['min_p']==.05
        original={**out,'messages':[{'role':'system','content':'Preserve the application instructions.'},
                                  {'role':'user','content':'reasoning probe'}]}
        frozen=copy.deepcopy(original)
        wire=adapter(original,author_template=True)
        assert original==frozen and '_strata_reasoning_mode' not in wire
        tag={'none':'ioff','high':'off','xhigh':'off'}.get(level,level)
        assert wire['messages'][-1]['content']=='{REASON:'+tag+'}\nreasoning probe'
        assert wire['messages'][0]==original['messages'][0]
        if strata:
            _,_,kwargs=strata['openai_to_messages'](out)
            if level=='none':assert kwargs=={'enable_thinking':False}
            else:assert kwargs['reasoning_effort']==('xhigh' if level in ('high','xhigh','ultra') else level)
            if level=='ultra':assert kwargs['reasoning_effort']=='xhigh'
            if template:
                rendered=template.render(messages=wire['messages'],tools=None,add_generation_prompt=True,**kwargs)
                reference_effort='off' if level in ('none','high','xhigh') else level
                reference=template.render(messages=frozen['messages'],tools=None,add_generation_prompt=True,
                    reasoning_effort=reference_effort,enable_thinking=level!='none')
                assert rendered==reference,(level,'template mode differs from real reference')
                proof.append({'mode':level,'converter':converter,'wire_effort':transport,
                              'render_sha256':hashlib.sha256(rendered.encode()).hexdigest(),'reference_match':True})
if template:
    for original,wire,expected in adaptive_vectors:
        if not original['messages'][0]['content']:continue
        rendered=template.render(messages=wire['messages'],tools=None,add_generation_prompt=True,
                                 reasoning_effort='xhigh',enable_thinking=True)
        reference=template.render(messages=original['messages'],tools=None,add_generation_prompt=True,
                                  reasoning_effort=expected or 'xhigh',enable_thinking=True)
        assert rendered==reference,'Adaptive did not activate the actual selected template construct'
        proof.append({'mode':'adaptive','selected_reasoning_mode':expected,'reference_match':True,
                      'render_sha256':hashlib.sha256(rendered.encode()).hexdigest()})
# Profile controls never affect tool records, original user content, or unrelated providers.
body={'_strata_reasoning_mode':'ultra','messages':[{'role':'user','content':[{'type':'text','text':'probe'},
      {'type':'image_url','image_url':{'url':'data:image/png;base64,fixture'}}]},
      {'role':'assistant','tool_calls':[{'id':'call-1'}]},{'role':'tool','content':'result','tool_call_id':'call-1'}]}
before=copy.deepcopy(body);wire=adapter(body,True)
assert body==before and wire['messages'][1:]==body['messages'][1:]
assert wire['messages'][0]['content'][1:]==body['messages'][0]['content']
assert adapter(wire,True) is wire
for invalid_mode in [None,{},[],42,'unknown']:
    assert '_strata_reasoning_mode' not in adapter({**body,'_strata_reasoning_mode':invalid_mode},True)
manual={'_strata_reasoning_mode':'high','messages':[{'role':'user','content':'{REASON:coder} probe'}]}
assert adapter(manual,True)['messages']==manual['messages']
assert adapter(body,False)['messages']==body['messages']
if args.receipt:
    args.receipt.write_text(json.dumps({'model_requests':0,'filter_checks':False,'vectors':proof,
        'strata_parser_sha256':hashlib.sha256(args.strata_source.read_bytes()).hexdigest(),
        'template_sha256':hashlib.sha256(args.template.read_bytes()).hexdigest()},indent=2)+'\n')
print('STRATA_REASONING_6_LEVELS_2_REAL_OWUI_CONVERTERS_PASSED'+('_ACTUAL_STRATA_PARSER_PASSED' if strata else ''))
