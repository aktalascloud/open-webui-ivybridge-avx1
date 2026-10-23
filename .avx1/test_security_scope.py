import json
from pathlib import Path
import tempfile
import unittest
from security_scope import review,verify_boundary


class SecurityScopeTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.backend=self.root/'backend/open_webui'
        path=self.backend/'retrieval/vector/dbs/chroma.py';path.parent.mkdir(parents=True)
        path.write_text('client.get_collection(name="fixture",embedding_function=None)',encoding='utf-8')

    def test_unrelated_or_new_chroma_findings_never_get_exempted(self):
        for package,identifier in [('chromadb','NEW-UNREVIEWED'),('other','CVE-2026-45829')]:
            with self.assertRaisesRegex(RuntimeError,'Unresolved'):
                review({'dependencies':[{'name':package,'version':'1.5.9','vulns':[{'id':identifier}]}]},self.root)

    def test_exact_http_server_advisory_has_an_explicit_scope_record(self):
        result=review({'dependencies':[{'name':'chromadb','version':'1.5.9','vulns':[{'id':'CVE-2026-45829'}]}]},self.root)
        self.assertEqual(len(result['reviewed_not_applicable']),1)
        self.assertEqual(result['boundary_proof']['collection_calls_with_embedding_function_none'],1)

    def test_server_import_or_remote_embedding_loading_invalidates_the_review(self):
        path=self.backend/'retrieval/vector/dbs/chroma.py'
        for source in ['from chromadb.server.fastapi import FastAPI','client.get_collection(embedding_function=untrusted)']:
            path.write_text(source,encoding='utf-8')
            with self.assertRaises(RuntimeError):verify_boundary(self.root)


if __name__=='__main__':unittest.main()
