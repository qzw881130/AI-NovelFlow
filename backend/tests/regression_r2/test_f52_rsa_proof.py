"""New multimodal proof is checked before #06/#09 workflow submission.

The upstream responses/workflow are explicit fixtures, not external-call evidence.
"""
import json

import pytest

from app.models.llm_log import LLMLog
from app.models.rsa_media import RsaMediaArtifact
from test_rsa_media import (db_session, chapter, fixture, base_setup, setup,
                            LLM, Remote, enqueue, run)


@pytest.mark.parametrize('mutation', ['swap', 'missing_part', 'hash', 'strip_proof', 'wire'])
def test_mismatched_llm_images_cannot_publish_or_submit(db_session, setup, mutation):
    class WrongImages(LLM):
        async def chat_completion(self, **kwargs):
            result = await super().chat_completion(**kwargs)
            log = db_session.get(LLMLog, result['llm_log_id'])
            parts = json.loads(log.user_prompt)
            if mutation == 'swap':
                parts[1], parts[2] = parts[2], parts[1]
            elif mutation == 'missing_part':
                parts[1] = {'type': 'text', 'text': 'image silently dropped'}
            elif mutation == 'hash':
                parts[1]['image_evidence'] = {'sha256': '0' * 64}
            elif mutation == 'strip_proof':
                log.request_info = None
                for part in parts:
                    part.pop('image_evidence', None)
            else:
                info = json.loads(log.request_info)
                info['payload']['messages'][1]['content'][1] = {'type': 'text', 'text': 'wire dropped the image'}
                log.request_info = json.dumps(info)
            log.user_prompt = json.dumps(parts, ensure_ascii=False)
            db_session.commit()
            return result

    remote = Remote()
    row, _, _ = run(db_session, enqueue(db_session, setup[3][0]),
                    llm=WrongImages(db_session), remote=remote)
    assert row.status == 'FAILED', 'Unverified image input reached a successful artifact'
    assert not db_session.query(RsaMediaArtifact).count()
    assert remote.submits == 0
