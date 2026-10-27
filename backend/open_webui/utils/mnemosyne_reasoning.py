"""Mnemosyne task-to-reasoning selector; no memory store or model execution.

Adapted from Strata-Mnemosyne serve/server.py, MIT.
Copyright (c) 2026 Niko1221 and the Strata contributors.
Source commit: 2ac28be317c8ecbabc935f6153333506fb80f3e2
See NOTICE-MNEMOSYNE.txt. Local changes: stable summation/tie handling.
"""
import math
import re
from collections import Counter

REASON_AUTO = {
    'coder': frozenset(['api', 'async', 'backend', 'bug', 'build', 'cache', 'caching', 'class', 'cli', 'code', 'coding', 'compile', 'concurrency', 'css', 'database', 'dependency', 'deploy', 'distributed', 'docker', 'endpoint', 'exception', 'fix', 'frontend', 'function', 'git', 'golang', 'grpc', 'html', 'implement', 'java', 'javascript', 'json', 'kubernetes', 'latency', 'leak', 'library', 'lint', 'merge', 'microservice', 'module', 'null', 'package', 'pip', 'program', 'pytest', 'python', 'queue', 'race', 'react', 'rebase', 'redis', 'refactor', 'regex', 'rust', 'schema', 'script', 'server', 'sql', 'stack', 'swift', 'throughput', 'trace', 'typescript', 'undefined', 'unittest', 'venv', 'vue', 'websocket']),
    'house': frozenset(['abscess', 'ailment', 'allergies', 'allergy', 'autoimmune', 'bacteria', 'benign', 'broken', 'bug', 'cardiology', 'cause', 'clinic', 'condition', 'coredump', 'cough', 'crash', 'cyst', 'debug', 'debugging', 'dermatology', 'diagnose', 'diagnosis', 'differential', 'disease', 'dizziness', 'dizzy', 'doctor', 'eliminate', 'elimination', 'error', 'exception', 'failing', 'fails', 'failure', 'fatigue', 'fracture', 'headache', 'heisenbug', 'hospital', 'hypothesis', 'illness', 'infection', 'inflammation', 'intermittent', 'lesion', 'logs', 'lump', 'malady', 'malignant', 'medical', 'medication', 'medicine', 'migraine', 'mystery', 'nausea', 'neurology', 'oncology', 'oom', 'palpitations', 'patient', 'prescription', 'prognosis', 'rash', 'reflux', 'regression', 'remedy', 'rheumatology', 'root', 'sarcoma', 'segfault', 'sprain', 'stack', 'suddenly', 'surgery', 'surgical', 'swelling', 'symptom', 'symptoms', 'therapy', 'timeout', 'trace', 'treatment', 'triage', 'tumor', 'tumour', 'vertigo', 'virus', 'worked']),
    'stark': frozenset(['architect', 'architecture', 'blueprint', 'capacity', 'cluster', 'design', 'diagram', 'failover', 'foresight', 'infrastructure', 'integration', 'monolith', 'platform', 'redundancy', 'requirements', 'roadmapping', 'scalable', 'scaling', 'service', 'solutions', 'systems', 'topology', 'tradeoff', 'visionary', 'whiteboard']),
    '007': frozenset(['agent', 'agentic', 'automation', 'autonomous', 'backpressure', 'batch', 'cron', 'daemon', 'deterministic', 'execute', 'fallback', 'fleet', 'job', 'monitor', 'multi-step', 'orchestrate', 'orchestration', 'pipeline', 'retry', 'runbook', 'schedule', 'self-healing', 'tool-calls', 'unattended', 'watchdog', 'workflow']),
    'ultra': frozenset(['acceptance', 'benchmark', 'careful', 'complete', 'deliverable', 'deliverables', 'eval', 'evaluation', 'final', 'flawless', 'perfect', 'perfection', 'polish', 'production', 'release', 'review', 'reviews', 'ship', 'sign-off', 'validation', 'verify']),
    'hyper': frozenset(['audit', 'breakdown', 'categorize', 'decompose', 'deconstruct', 'deconstruction', 'dissect', 'exhaustive', 'frameworks', 'granularity', 'mece', 'outline', 'sections', 'segmentation', 'structure', 'taxonomy']),
    'spoon': frozenset(['archival', 'bibliography', 'citation', 'cite', 'claims', 'dossier', 'evidence', 'experts', 'fact-checking', 'facts', 'literature', 'meta-analysis', 'methodology', 'panel', 'paper', 'papers', 'peer-reviewed', 'referencing', 'research', 'rigor', 'sources', 'studies', 'study', 'survey']),
    'deeptree': frozenset(['alternative', 'branch', 'causal', 'causality', 'contingency', 'counterfactual', 'decision', 'decision-tree', 'decisions', 'dependency', 'options', 'path', 'plan', 'planning', 'prune', 'pruning', 'roadmap', 'scenarios', 'stages', 'strategic', 'strategy', 'tree']),
    'omni': frozenset(['across', 'analogy', 'connections', 'convergent', 'cross-domain', 'culture', 'domains', 'everything', 'fields', 'holistic', 'interdisciplinary', 'isomorphism', 'lenses', 'metaphor', 'paradigm', 'parallel', 'synthesis', 'synthesize', 'unified']),
    'socrates': frozenset(['assumption', 'assumptions', 'clarify', 'counterexample', 'critique', 'define', 'definition', 'elenchus', 'examine', 'gaps', 'implication', 'implications', 'interrogate', 'meaning', 'premise', 'premises', 'probe', 'question', 'questions', 'refute', 'socratic']),
    'teacher': frozenset(['beginner', 'crash-course', 'eli5', 'explain', 'foundations', 'guide', 'intro', 'introduction', 'learn', 'learned', 'lesson', 'mentor', 'plain', 'primer', 'simply', 'step-by-step', 'teach', 'teaching', 'tutorial', 'understand', 'walkthrough']),
    'einstein': frozenset(['creative', 'creativity', 'divergent', 'ideas', 'ideation', 'imagine', 'improbable', 'invent', 'invention', 'lateral', 'novel', 'novelty', 'original', 'serendipity', 'speculative', 'surprising', 'thought-experiment', 'unusual', 'what-if']),
    'brainstorm': frozenset(['brainstorm', 'generate', 'ideate', 'list', 'many', 'quickly', 'solutions']),
    'business': frozenset(['acquisition', 'b2b', 'b2c', 'boardroom', 'brand', 'business', 'churn', 'company', 'competitor', 'competitors', 'customer', 'customers', 'differentiation', 'funding', 'funnel', 'go-to-market', 'growth', 'gtm', 'investor', 'market', 'marketing', 'merger', 'monetization', 'okrs', 'pitch', 'positioning', 'pricing', 'profit', 'retention', 'revenue', 'saas', 'sales', 'startup', 'valuation']),
    'matlock': frozenset(['advocacy', 'arbitration', 'attorney', 'brief', 'compliance', 'contract', 'contracts', 'copyright', 'counsel', 'court', 'deposition', 'felony', 'gdpr', 'injunction', 'law', 'lawsuit', 'lawyer', 'legal', 'liability', 'litigation', 'misdemeanor', 'objection', 'patent', 'precedent', 'privacy', 'procedural', 'regulation', 'regulations', 'statute', 'subpoena', 'testimony', 'tort', 'trademark', 'verdict', 'witness']),
    'musk': frozenset(['aerodynamic', 'battery', 'costs', 'energy', 'feasible', 'first-principles', 'fundamental', 'manufacturing', 'material', 'materials', 'orbital', 'physical', 'physics', 'propulsion', 'rocket', 'silicon', 'thruster', 'tolerances', 'volumetric', 'wafer']),
    'curie': frozenset(['anatomy', 'atom', 'atoms', 'biology', 'chemistry', 'crispr', 'dna', 'enzyme', 'evolution', 'experiment', 'experiments', 'gene', 'genes', 'hormone', 'laboratory', 'measurement', 'mechanism', 'mechanistic', 'molecule', 'molecules', 'mrna', 'neuron', 'physiology', 'protein', 'radioactivity', 'rna', 'science', 'scientific', 'truth', 'vaccine']),
    'story': frozenset(['antagonist', 'chapter', 'character', 'characters', 'climax', 'dialogue', 'ending', 'epic', 'fiction', 'lyrical', 'monologue', 'motif', 'narrative', 'novel', 'plot', 'poem', 'poetry', 'prose', 'protagonist', 'scene', 'screenplay', 'screenwriting', 'stories', 'story', 'tale', 'theme', 'themes', 'twist', 'writing']),
    'comedy': frozenset(['amuse', 'bit', 'comedian', 'funny', 'humor', 'humorous', 'humour', 'joke', 'jokes', 'laugh', 'laughing', 'meme', 'pun', 'satire', 'silly', 'stand-up', 'witty']),
    'joe': frozenset(['casual', 'everyday', 'folks', 'friend', 'honestly', 'regular', 'relatable']),
    'prompt': frozenset(['chain-of-thought', 'claude', 'context-window', 'few-shot', 'gpt', 'instruct', 'instruction-tuning', 'llm', 'meta-prompt', 'prompt', 'prompt-template', 'prompting', 'prompts', 'system-prompt', 'token-budget']),
    'holodeck': frozenset(['adversarial', 'argue', 'both-sides', 'debate', 'debates', 'devil-advocate', 'discuss', 'discussion', 'opposing', 'panelists', 'perspectives', 'roundtable', 'simulate', 'sparring', 'symposium', 'tribunal', 'versus']),
    'vader': frozenset(['authority', 'choice', 'choose', 'command', 'commit', 'consequential', 'decide', 'decision', 'decisions', 'decree', 'duty', 'empire', 'irreversible', 'leadership', 'mandate', 'order', 'resolve', 'ruthless', 'sacrifice', 'ultimatum']),
    'neo': frozenset(['awake', 'belief', 'believe', 'consciousness', 'control', 'determinism', 'doubt', 'glitch', 'illusion', 'matrix', 'morpheus', 'prophecy', 'reality', 'red-pill', 'reframe', 'simulation-hypothesis', 'skeptical', 'zion']),
    'joker': frozenset(['absurd', 'anarchic', 'anarchy', 'chaos', 'disrupt', 'fragile', 'invert', 'irony', 'irreverent', 'mad', 'paradox', 'provocateur', 'subvert', 'topsy-turvy', 'trick', 'unconventional', 'upend']),
    'quinn': frozenset(['bold', 'confident', 'daring', 'edgy', 'flair', 'opinion', 'opinions', 'personality', 'playful', 'unapologetic']),
    'logic': frozenset(['axiom', 'consistent', 'contradiction', 'deduce', 'deduction', 'fallacy', 'first', 'formal', 'logic', 'logical', 'mathematics', 'modus-ponens', 'principles', 'proof', 'prove', 'proving', 'soundness', 'syllogism', 'tautology', 'theorem', 'validity']),
    '007+coder': frozenset(['agentic', 'builds', 'circuit-breaker', 'idempotent', 'orchestration', 'rate-limiter', 'workers']),
    'stark+coder': frozenset(['apis', 'frontends', 'microservices']),
    'ultra+coder': frozenset(['clean', 'code-review', 'linting', 'refactoring']),
    'deeptree+spoon': frozenset(['roadmaps', 'thesis']),
    'hyper+socrates': frozenset(['dissertation', 'essay', 'structuring']),
    'musk+business': frozenset(['fundamentals', 'manufacturing']),
    'curie+teacher': frozenset(['crispr', 'lessons']),
    'joe+comedy': frozenset(['relatable']),
    'socrates+teacher': frozenset(['argument', 'drill', 'drills', 'ethics', 'exam', 'exams', 'flashcards', 'homework', 'memorize', 'philosophical', 'philosophy', 'position', 'quiz', 'quizzes', 'rebuttal', 'tutor', 'tutoring']),
    'einstein+pkd': frozenset(['android', 'cyberpunk', 'dystopia', 'dystopian', 'fantasy', 'paranoid', 'sci-fi', 'scifi', 'simulation', 'what-if', 'worldbuilding']),
    'prompt+prompt': frozenset(['optimize', 'tune']),
    'house+teacher': frozenset(['diagnostic', 'layperson', 'patient-friendly', 'second-opinion']),
    'matlock+hyper': frozenset(['addendum', 'boilerplate', 'clause', 'clauses', 'fine-print', 'indemnity', 'redline']),
    'socrates+matlock': frozenset(['briefs', 'cross-examination', 'dissent', 'jurisprudence', 'policies', 'policy']),
    'joker+comedy': frozenset(['deadpan', 'improv', 'one-liner', 'one-liners', 'punchline', 'punchlines', 'roast', 'roasts']),
    'pkd+comedy': frozenset(['caricature', 'farce', 'gallows', 'parody', 'tragicomic']),
    'stark+prompt': frozenset(['guardrail', 'guardrails', 'output-format', 'persona', 'personas', 'system-card']),
    'joker+socrates': frozenset(['advocate', 'advocates', 'goad', 'raconteur']),
    'business+hyper': frozenset(['five-forces', 'segment', 'segments', 'swot', 'white-space']),
    'musk+logic': frozenset(['defensibility', 'moat', 'thermodynamics', 'unit-economics']),
    'neo+story': frozenset(['deus-ex-machina', 'foreshadow', 'peripeteia', 'reversal', 'twists']),
}

_DF=Counter(word for words in REASON_AUTO.values() for word in words)
REASON_AUTO_W={name:{word:1.0/_DF[word] for word in words} for name,words in REASON_AUTO.items()}

def reason_auto_pick(text: str) -> str | None:
    hits=set(re.findall(r"[a-z0-9][a-z0-9+#'-]{1,}",(text or '').lower()))
    best,best_score,tied=None,0.0,False
    for name,weights in REASON_AUTO_W.items():
        score=math.fsum(weights[word] for word in sorted(hits) if word in weights)
        if score>best_score+1e-12:
            best,best_score,tied=name,score,False
        elif abs(score-best_score)<=1e-12 and score>0 and name!=best:
            tied=True
    return best if best is not None and best_score>=0.4 and not tied else None
