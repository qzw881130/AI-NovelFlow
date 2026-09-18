"""Keyframe authoring and sole RSA image admission; legacy generation is retired."""
import json
from copy import deepcopy
from types import SimpleNamespace
from fastapi import HTTPException
from app.models.shot import Shot
from app.services.chapter_governance import require_source
from app.services.rsa_image_service import RsaImageService,_frame_patch
from app.services.rsa_media_contract import current_primary,keyframe_parent,pin_rsa
from app.services.keyframe_reference_contract import snapshot_target
from app.services import appearance_image_contract as images
from app.services.resolved_asset_images import IMAGE_POLICY


class ShotKeyframeService:
    @staticmethod
    def _read_reference_payload(url):
        data,_=images.image_bytes(url,IMAGE_POLICY)
        return images.url_to_local_path(url),data

    async def generate_keyframe_image(self,db,shot_id,frame_index,workflow_id=None,skip_llm_when_prompt_exists=False,parent_task_id=None,batch_order=None,execution_purpose='production'):
        if execution_purpose!='production':raise HTTPException(410,'BENCHMARK_RUNTIME_RETIRED')
        result=RsaImageService(db).enqueue(shot_id,stage='KEYFRAME',frame_index=frame_index,workflow_id=workflow_id,
            skip_prompt=skip_llm_when_prompt_exists,parent_task_id=parent_task_id,batch_order=batch_order)
        return True,result['data']['taskId'],'角色外观与分镜最终资产已固定'

    async def generate_keyframe_descriptions(self,*args,**kwargs):
        raise HTTPException(410,'LEGACY_KEYFRAME_PLANNER_RETIRED: 使用视频导演规划入口')

    async def upload_keyframe_image(self,*args,**kwargs):
        raise HTTPException(410,'UNVERIFIED_IMAGE_ADOPTION_RETIRED: 重新生成可信来源图')

    async def replace_keyframe_image(self,*args,**kwargs):
        raise HTTPException(410,'UNVERIFIED_IMAGE_ADOPTION_RETIRED: 重新生成可信来源图')

    async def upload_reference_image(self,*args,**kwargs):
        raise HTTPException(410,'UNVERIFIED_REFERENCE_UPLOAD_RETIRED')

    async def set_reference_image(self,db,shot_id,frame_index,mode='auto_select',reference_url=None):
        require_source(db,shot_id);shot=db.get(Shot,shot_id)
        if mode not in {'auto_select','custom','none'}:raise HTTPException(422,'INVALID_REFERENCE_MODE')
        if mode=='none':raise HTTPException(409,'KEYFRAME_RSA_LINEAGE_REFERENCE_REQUIRED')
        primary=current_primary(db,shot);pin_rsa(db,shot_id,primary.rsa_id,primary.data['rsa_hash'])
        candidate=SimpleNamespace(**{c.key:deepcopy(getattr(shot,c.key)) for c in Shot.__table__.columns});frames=json.loads(shot.keyframes or '[]')
        if not 0<=frame_index<len(frames):raise HTTPException(404,'关键帧不存在')
        frames[frame_index].update(reference_mode=mode,reference_image_url=reference_url)
        candidate.keyframes=json.dumps(frames,ensure_ascii=False)
        parent,_=keyframe_parent(db,candidate,frame_index,snapshot_target(candidate,frame_index),primary)
        _frame_patch(db,shot,frame_index,{'reference_mode':mode,'reference_image_url':parent.data['image']['url']});db.commit()
        return True,parent.data['image']['url'],'已设置同一分镜最终资产下的参考图'

    async def recover_benchmark_image(self,*args,**kwargs):
        raise HTTPException(410,'BENCHMARK_RUNTIME_RETIRED')
