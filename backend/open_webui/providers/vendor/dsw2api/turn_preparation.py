"""Shared, account-bound input preparation for every chat protocol/mode."""
from dataclasses import dataclass

from .image_inputs import ImageAttachment
from .execution_observer import phase


@dataclass
class PreparedTurn:
    session_id: str
    prompt: str
    ref_file_ids: list[str]
    retry_prompt: str
    retry_ref_file_ids: list[str]

    def completion_options(self):
        if not self.retry_ref_file_ids:
            return {}
        return {'ref_file_ids': self.ref_file_ids, 'retry_prompt': self.retry_prompt,
                'retry_ref_file_ids': self.retry_ref_file_ids}


def prepare_turn(acquired, prompt: str, attachments: tuple[ImageAttachment, ...] = (), *,
                 thinking: bool = False, model_type: str = 'default',
                 replay_digests: list[str] | None = None, observer=None) -> PreparedTurn:
    previous = getattr(acquired, 'previous_prompt', '')
    files = dict(getattr(acquired, 'image_files', {}))
    previous_refs = list(files.values())
    effective = acquired.prepare_prompt(prompt)
    with phase(observer, 'session_create'):
        session = acquired.create_session()
    uploaded = []
    for image in attachments:
        digest = image.asset.digest
        if digest not in files:
            with phase(observer, 'image_upload', image_count=1, image_bytes=len(image.asset.data)):
                files[digest] = acquired.adapter.files.upload(image.asset, thinking=thinking, model_type=model_type)
            uploaded.append(files[digest])
    if uploaded:
        with phase(observer, 'image_processing', image_count=len(uploaded)):
            acquired.adapter.files.wait_ready(uploaded)
    if files:
        # This is per-acquisition staging; the session is updated on chat success.
        acquired.stage_image_files(dict(list(files.items())[-64:]))
    refs = [files[image.asset.digest] for image in attachments if image.marker in effective]
    all_refs = [files[image.asset.digest] for image in attachments] if attachments else list(files.values())
    fallback = prompt
    if previous and not prompt.startswith(previous) and all_refs:
        fallback = previous + '\n' + prompt
        if attachments:
            all_refs = previous_refs + all_refs
    if replay_digests is not None:
        from .image_inputs import ImageError
        if any(digest not in files for digest in replay_digests):
            raise ImageError('Image references are unavailable; resend complete input and original images', 409)
        refs = all_refs = [files[digest] for digest in replay_digests]
        fallback = prompt
    return PreparedTurn(session, effective, refs, fallback, all_refs)
