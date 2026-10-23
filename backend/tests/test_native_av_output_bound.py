"""Reject-only native Temporal Anchor bounds, independent of mux repair."""
import copy
import json

import pytest

from app.services import continuous_clip_av as av
from test_continuous_clip_native_av import physical
from test_native_av_mux import result


@pytest.mark.parametrize('count,position,allowed', [(529,206,True),(782,293,False),(784,293,True),
                                                   (784,294,True),(784,295,False),(784,0,False),
                                                   (784,-1,False),(784,True,False)])
@pytest.mark.parametrize('acceptance',['new','approved'])
def test_temporal_bound_rejects_both_acceptance_paths_without_mutating_anchor(monkeypatch,count,position,allowed,acceptance):
    previous_frames=294 if count==529 else 529
    contract={'artifact_kind':av.NATIVE_CONTINUITY_OUTPUT,'capability':'TEMPORAL_EXTEND',
              'previous_clip':{'generated_by_task_id':'previous','physical_output':physical(previous_frames)},
              'temporal_anchor_manifest':{'anchors':[{'frame_position':position,'source':{'id':'target'}}]}}
    original=copy.deepcopy(contract);actual=physical(count);monkeypatch.setattr(av,'probe_clip_av',lambda _:actual)
    output={**actual,'physical_output_role':av.NATIVE_CONTINUITY_OUTPUT,'output_node_id':'65',
            'result_url':'/api/files/native.mp4','capability':'TEMPORAL_EXTEND','overlap_frames':39,
            'overlap_duration':1.625,'previous':contract['previous_clip']}
    def accept():
        if acceptance=='new':return av.continuity_output_metadata(result(),contract,'unused','/api/files/native.mp4')
        return av.validate_native_output({'physical_output':output,'execution_contract':contract},output['result_url'],'unused')
    if allowed:accept()
    else:
        with pytest.raises(ValueError,match='NATIVE_TEMPORAL_ANCHOR_OUTPUT_BOUND_VIOLATION') as exc:accept()
        details=json.loads(str(exc.value).split(': ',1)[1]);assert details['effective_anchor_frame']==position
        assert details['replacement_frames']==count-(previous_frames-39)
    assert contract==original
