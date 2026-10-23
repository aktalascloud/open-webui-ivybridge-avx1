"""Narrow applicability review for unmodified Chroma's standalone HTTP server."""
import ast
from pathlib import Path

CHROMA_SERVER_IDS = {
    'PYSEC-2026-311','CVE-2026-45829','GHSA-f4j7-r4q5-qw2c',
    'PYSEC-2026-3814','CVE-2026-45833','GHSA-36p7-vc44-83pf',
    'PYSEC-2026-3815','CVE-2026-45831','GHSA-xph7-9rjv-w5fr',
    'PYSEC-2026-3813','CVE-2026-45830','GHSA-2wm9-hf6c-p5cr',
}


def verify_boundary(root):
    backend=Path(root)/'backend/open_webui'
    for path in backend.rglob('*.py'):
        source=path.read_text('utf-8')
        if '/api/v2/tenants' in source:
            raise RuntimeError('A Chroma HTTP route appears in the application; security review required')
        tree=ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,ast.Import) and any(item.name.startswith('chromadb.server') for item in node.names):
                raise RuntimeError('Chroma standalone server is imported')
            if isinstance(node,ast.ImportFrom) and ((node.module or '').startswith('chromadb.server') or
                    node.module=='chromadb' and any(item.name=='server' for item in node.names)):
                raise RuntimeError('Chroma standalone server is imported')
    path=backend/'retrieval/vector/dbs/chroma.py'
    tree=ast.parse(path.read_text('utf-8'))
    collections=0
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in {'get_collection','get_or_create_collection','create_collection'}:
            value=next((item.value for item in node.keywords if item.arg=='embedding_function'),None)
            if not isinstance(value,ast.Constant) or value.value is not None:
                raise RuntimeError('Collection embedding code loading changed; security review required')
            collections+=1
    if collections<1:raise RuntimeError('Unknown Chroma client boundary')
    return {'deployment':'Open WebUI embedded/client integration; no standalone Chroma HTTP server',
            'collection_calls_with_embedding_function_none':collections,
            'scope':'Only the four named Chroma HTTP-server advisories; does not assert a standalone/external server is patched'}


def review(report,root):
    reviewed=[];unresolved=[];proof=None
    for dependency in report['dependencies']:
        if dependency.get('skip_reason'):raise RuntimeError('Dependency audit skipped a package; publication blocked')
        for finding in dependency.get('vulns',[]):
            identities={finding['id'],*finding.get('aliases',[])}
            if dependency['name']=='chromadb' and dependency['version']=='1.5.9' and identities & CHROMA_SERVER_IDS:
                if proof is None:proof=verify_boundary(root)
                reviewed.append({'package':'chromadb','version':'1.5.9','id':finding['id'],'aliases':finding.get('aliases',[]),
                                 'assessment':'not applicable to the shipped embedded/client deployment'})
            else:unresolved.append({'package':dependency['name'],'version':dependency['version'],'id':finding['id']})
    if unresolved:raise RuntimeError('Unresolved dependency advisories: '+str(unresolved))
    return {'unresolved':[],'reviewed_not_applicable':reviewed,'boundary_proof':proof}
