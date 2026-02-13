from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.models.test_case import TestCase
from app.models.novel import Novel, Chapter, Character

router = APIRouter()


@router.get("/", response_model=dict)
async def list_test_cases(
    type: Optional[str] = None,
    is_preset: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """获取测试用例列表"""
    query = db.query(TestCase).order_by(TestCase.created_at.desc())
    
    if type:
        query = query.filter(TestCase.type == type)
    if is_preset is not None:
        query = query.filter(TestCase.is_preset == is_preset)
    
    test_cases = query.all()
    
    # 获取关联的小说信息
    result = []
    for tc in test_cases:
        novel = db.query(Novel).filter(Novel.id == tc.novel_id).first()
        
        # 获取统计数据
        chapter_count = db.query(Chapter).filter(Chapter.novel_id == tc.novel_id).count()
        character_count = db.query(Character).filter(Character.novel_id == tc.novel_id).count()
        
        result.append({
            "id": tc.id,
            "name": tc.name,
            "description": tc.description,
            "type": tc.type,
            "isActive": tc.is_active,
            "isPreset": tc.is_preset,
            "novelId": tc.novel_id,
            "novelTitle": novel.title if novel else "未知",
            "chapterCount": chapter_count,
            "characterCount": character_count,
            "expectedCharacterCount": tc.expected_character_count,
            "expectedShotCount": tc.expected_shot_count,
            "notes": tc.notes,
            "createdAt": tc.created_at.isoformat() if tc.created_at else None,
        })
    
    return {
        "success": True,
        "data": result
    }


@router.get("/{test_case_id}", response_model=dict)
async def get_test_case(test_case_id: str, db: Session = Depends(get_db)):
    """获取测试用例详情"""
    tc = db.query(TestCase).filter(TestCase.id == test_case_id).first()
    if not tc:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    
    # 获取小说详情
    novel = db.query(Novel).filter(Novel.id == tc.novel_id).first()
    
    # 获取章节列表
    chapters = db.query(Chapter).filter(Chapter.novel_id == tc.novel_id).order_by(Chapter.number).all()
    
    # 获取角色列表
    characters = db.query(Character).filter(Character.novel_id == tc.novel_id).all()
    
    return {
        "success": True,
        "data": {
            "id": tc.id,
            "name": tc.name,
            "description": tc.description,
            "type": tc.type,
            "isActive": tc.is_active,
            "isPreset": tc.is_preset,
            "expectedCharacterCount": tc.expected_character_count,
            "expectedShotCount": tc.expected_shot_count,
            "notes": tc.notes,
            "novel": {
                "id": novel.id if novel else None,
                "title": novel.title if novel else None,
                "author": novel.author if novel else None,
                "description": novel.description if novel else None,
            },
            "chapters": [
                {
                    "id": c.id,
                    "number": c.number,
                    "title": c.title,
                    "contentLength": len(c.content) if c.content else 0,
                }
                for c in chapters
            ],
            "characters": [
                {
                    "id": c.id,
                    "name": c.name,
                    "hasImage": c.image_url is not None,
                }
                for c in characters
            ],
            "createdAt": tc.created_at.isoformat() if tc.created_at else None,
        }
    }


@router.post("/", response_model=dict)
async def create_test_case(data: dict, db: Session = Depends(get_db)):
    """创建测试用例"""
    # 验证小说存在
    novel = db.query(Novel).filter(Novel.id == data.get('novelId')).first()
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    
    test_case = TestCase(
        name=data.get('name'),
        description=data.get('description'),
        novel_id=data.get('novelId'),
        type=data.get('type', 'full'),
        expected_character_count=data.get('expectedCharacterCount'),
        expected_shot_count=data.get('expectedShotCount'),
        notes=data.get('notes'),
        is_preset=False,  # 用户创建的不是预设
    )
    db.add(test_case)
    db.commit()
    db.refresh(test_case)
    
    return {
        "success": True,
        "data": {
            "id": test_case.id,
            "name": test_case.name,
            "novelId": test_case.novel_id,
            "type": test_case.type,
        }
    }


@router.put("/{test_case_id}", response_model=dict)
async def update_test_case(test_case_id: str, data: dict, db: Session = Depends(get_db)):
    """更新测试用例"""
    tc = db.query(TestCase).filter(TestCase.id == test_case_id).first()
    if not tc:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    
    if "name" in data:
        tc.name = data["name"]
    if "description" in data:
        tc.description = data["description"]
    if "type" in data:
        tc.type = data["type"]
    if "isActive" in data:
        tc.is_active = data["isActive"]
    if "expectedCharacterCount" in data:
        tc.expected_character_count = data["expectedCharacterCount"]
    if "expectedShotCount" in data:
        tc.expected_shot_count = data["expectedShotCount"]
    if "notes" in data:
        tc.notes = data["notes"]
    
    db.commit()
    db.refresh(tc)
    
    return {
        "success": True,
        "data": {
            "id": tc.id,
            "name": tc.name,
            "type": tc.type,
            "isActive": tc.is_active,
        }
    }


@router.delete("/{test_case_id}")
async def delete_test_case(test_case_id: str, db: Session = Depends(get_db)):
    """删除测试用例"""
    tc = db.query(TestCase).filter(TestCase.id == test_case_id).first()
    if not tc:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    
    # 预设测试用例不能删除
    if tc.is_preset:
        raise HTTPException(status_code=403, detail="预设测试用例不能删除")
    
    db.delete(tc)
    db.commit()
    
    return {"success": True, "message": "删除成功"}


@router.post("/{test_case_id}/run")
async def run_test_case(
    test_case_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """运行测试用例"""
    tc = db.query(TestCase).filter(TestCase.id == test_case_id).first()
    if not tc:
        raise HTTPException(status_code=404, detail="测试用例不存在")
    
    # 根据测试类型启动不同的任务
    if tc.type in ["full", "character"]:
        # 启动角色解析任务
        background_tasks.add_task(
            parse_characters_task,
            tc.novel_id
        )
    
    return {
        "success": True,
        "message": f"测试用例 '{tc.name}' 已开始运行",
        "data": {
            "testCaseId": tc.id,
            "type": tc.type,
        }
    }


# 初始化预设测试用例
async def init_preset_test_cases(db: Session):
    """初始化预设测试用例"""
    # 检查是否已存在小马过河测试用例
    existing = db.query(TestCase).filter(TestCase.is_preset == True).first()
    if existing:
        return
    
    # 创建小马过河小说
    from app.api.novels import parse_characters_task
    
    novel = Novel(
        title="小马过河（章节版）",
        author="AI测试用例",
        description="经典童话故事，用于测试AI角色解析和分镜生成功能",
        is_preset=True,
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    
    # 创建8个章节
    chapters_data = [
        {
            "title": "第一章：妈妈的嘱托",
            "content": """小马长大了，皮毛变得油亮光滑，四肢也越来越有力气。一天，马妈妈牵着小马的手，温柔地说："孩子，你已经是能帮妈妈做事的小大人了。家里的麦子吃完了，你帮妈妈把这半袋麦子送到河对岸的磨坊去吧，好吗？"

小马眼睛一亮，兴奋地甩了甩尾巴："太好了妈妈！我保证完成任务！"他小心翼翼地接过沉甸甸的麦子，搭在自己的背上，又蹭了蹭马妈妈的脸颊，转身就向门外跑去。马妈妈看着他欢快的背影，大声叮嘱道："孩子，路上要小心，遇到不懂的事，多问问身边的长辈哦！"

小马一边跑一边喊："知道啦妈妈！"风拂过他的耳边，路边的小草和野花轻轻点头，仿佛在为他加油，小马心里美滋滋的，觉得自己一定能顺利完成妈妈交给的任务。"""
        },
        {
            "title": "第二章：遇见湍急的小河",
            "content": """小马跑了一会儿，眼前出现了一条小河。河水哗哗地流着，波光粼粼的水面上，偶尔有小鱼跳出水面，又"扑通"一声钻进水里，溅起一朵朵小小的水花。可是，小河上没有桥，也没有船，只有深深的河水挡在面前。

小马停下脚步，皱起了眉头。他低头看了看背上的麦子，又看了看湍急的河水，心里犯了难："这河水到底深不深呀？我能过去吗？要是河水太深，把我冲走了怎么办？麦子也会被打湿的……"

他想起妈妈说的话，遇到不懂的事要多问长辈。于是，小马抬起头，四处张望，希望能找到可以请教的人。就在这时，他看到不远处的草地上，有一头老牛正在悠闲地吃草。"""
        },
        {
            "title": "第三章：老牛的回答",
            "content": """小马赶紧跑过去，恭恭敬敬地对老牛鞠了一躬，轻声问道："牛伯伯，牛伯伯，请问您知道这条河深不深呀？我要把麦子送到河对岸的磨坊去，能过得去吗？"

老牛抬起头，慢悠悠地看了看小河，又看了看小马，笑着说："孩子，这河一点也不深，才到我的小腿肚呢！你放心大胆地走过去，肯定没问题，水清清的，还能看到河底的小石头呢。"

小马听了，心里一下子踏实了许多。他连忙对老牛说："谢谢牛伯伯！"说完，就转身准备向河边走去，心里想着：原来河水这么浅，看来我很快就能完成任务，回到妈妈身边了。"""
        },
        {
            "title": "第四章：松鼠的警告",
            "content": """就在小马快要走到河边的时候，突然有一只小松鼠从树上跳了下来，飞快地跑到他面前，急急忙忙地拉住他的蹄子，大声喊道："别过去！别过去！你不能过河！"

小马被小松鼠吓了一跳，连忙停下脚步，疑惑地问："小松鼠，为什么不能过河呀？牛伯伯说河水很浅，才到他的小腿肚呢。"

小松鼠皱着眉头，眼睛红红的，着急地说："你可别听老牛胡说！这条河可深啦！昨天，我的好朋友就是不小心掉进这条河里，被河水冲走了，再也没有回来！我亲眼看到的，河水都快把我淹没了，你这么小，一进去就会被冲走的！"

小马听了小松鼠的话，又害怕起来。他挠了挠头，心里犯了嘀咕：牛伯伯说河水浅，小松鼠说河水深，到底谁说的是对的呀？我到底该不该过河呢？"""
        },
        {
            "title": "第五章：犹豫的小马",
            "content": """小马站在河边，左看看湍急的河水，右想想老牛和小松鼠的话，拿不定主意。他一会儿想起老牛温和的笑容，觉得河水应该很浅；一会儿又想起小松鼠着急的样子，觉得河水肯定很深。

他低下头，看了看背上的麦子，心里更着急了：妈妈还等着我把麦子送到磨坊呢，要是我一直在这里犹豫，耽误了时间，妈妈一定会担心的。可是，要是我贸然过河，万一河水真的很深，我被冲走了，怎么办？

小马越想越犹豫，他一会儿抬起脚，想要迈出第一步，一会儿又赶紧把脚收回来，不敢往前挪一步。河水依旧哗哗地流着，仿佛在催促他，又仿佛在嘲笑他的胆小。"""
        },
        {
            "title": "第六章：妈妈的启发",
            "content": """犹豫了好久，小马还是没有勇气过河。他想：不如我先回家问问妈妈，妈妈一定知道河水到底深不深。于是，小马掉转方向，背着麦子，慢悠悠地向家里走去。

回到家，马妈妈看到小马背着麦子回来了，疑惑地问："孩子，你怎么回来了？难道没有送到磨坊去吗？"

小马低下头，委屈地把自己遇到的事告诉了马妈妈："妈妈，我走到河边，看到河水很湍急，就问了牛伯伯，牛伯伯说河水很浅，可是小松鼠说河水很深，还说他的好朋友被河水冲走了，我不敢过河，就回来了。"

马妈妈听了，笑着摸了摸小马的头，温柔地说："孩子，牛伯伯和小松鼠说的都没有错，可是他们为什么说的不一样呢？"小马摇了摇头，不知道答案。马妈妈又说："因为牛伯伯长得高大，河水到他的小腿肚，自然很浅；而小松鼠长得矮小，河水对他来说，就很深了。"""
        },
        {
            "title": "第七章：勇敢地尝试",
            "content": """小马听了妈妈的话，恍然大悟，拍了拍自己的脑袋："哦！原来如此！我怎么没有想到呢？"马妈妈笑着说："孩子，遇到事情，不能只听别人的话，要自己去尝试一下，才能知道真相。别人的经验，不一定适合自己呀。"

小马点了点头，心里充满了勇气。他再次背起麦子，对马妈妈说："妈妈，我知道了！我现在就去河边，自己试一试，一定能顺利过河，把麦子送到磨坊去！"

马妈妈欣慰地笑了："好孩子，去吧，妈妈相信你！记住，勇敢一点，遇到困难不要退缩，自己去尝试，才能成长。"小马用力点了点头，转身向河边跑去，这一次，他的脚步坚定而有力。"""
        },
        {
            "title": "第八章：顺利过河，收获成长",
            "content": """小马再次来到河边，没有再犹豫，他深吸一口气，小心翼翼地抬起蹄子，踩进了河里。河水凉凉的，刚好没过他的脚踝，既不像老牛说的那么浅，也不像小松鼠说的那么深。

他一步一步，慢慢地向河对岸走去，一边走一边留意着脚下的石头，生怕滑倒。河水轻轻流过他的蹄子，小鱼在他身边游来游去，仿佛在为他加油。小马心里越来越有信心，脚步也越来越稳。

很快，小马就走到了河对岸。他高兴地甩了甩身上的水珠，看了看背上的麦子，完好无损，心里美滋滋的。他回头看了看小河，心里暗暗想：原来，只要自己勇敢地去尝试，就没有克服不了的困难。

小马背着麦子，飞快地向磨坊跑去，顺利地把麦子交给了磨坊主。完成任务后，他又开开心心地回了家，向妈妈分享自己的收获。从那以后，小马变得更加勇敢、更加独立，再也不是那个遇到困难就退缩的小不点了。"""
        },
    ]
    
    for idx, ch_data in enumerate(chapters_data, 1):
        chapter = Chapter(
            novel_id=novel.id,
            number=idx,
            title=ch_data["title"],
            content=ch_data["content"],
        )
        db.add(chapter)
    
    # 更新章节数
    novel.chapter_count = len(chapters_data)
    db.commit()
    
    # 创建测试用例
    test_case = TestCase(
        name="小马过河 - 完整流程测试",
        description="经典童话故事，包含4个主要角色，8个章节，用于测试完整的AI解析、角色生成、分镜生成和视频合成流程",
        novel_id=novel.id,
        type="full",
        is_preset=True,
        is_active=True,
        expected_character_count=4,
        expected_shot_count=8,
        notes="主要角色：小马、马妈妈、老牛、小松鼠",
    )
    db.add(test_case)
    db.commit()
    
    print(f"[初始化] 已创建预设测试用例: {test_case.name}")


from fastapi import BackgroundTasks
from app.services.deepseek import DeepSeekService

deepseek_service = DeepSeekService()


async def parse_characters_task(novel_id: str):
    """后台任务：解析小说文本提取角色"""
    from app.core.database import SessionLocal
    import json
    
    db = SessionLocal()
    try:
        print(f"[测试任务] 开始解析小说 {novel_id} 的角色")
        
        # 获取所有章节内容
        chapters = db.query(Chapter).filter(Chapter.novel_id == novel_id).all()
        full_text = "\n\n".join([c.content for c in chapters if c.content])[:10000]
        
        # 调用 DeepSeek 解析文本
        result = await deepseek_service.parse_novel_text(full_text)
        
        if "error" in result:
            print(f"[测试任务] 解析失败: {result['error']}")
            return
        
        characters_data = result.get("characters", [])
        print(f"[测试任务] 识别到 {len(characters_data)} 个角色")
        
        # 创建角色
        for char_data in characters_data:
            name = char_data.get("name", "").strip()
            if not name:
                continue
                
            existing = db.query(Character).filter(
                Character.novel_id == novel_id,
                Character.name == name
            ).first()
            
            if not existing:
                character = Character(
                    novel_id=novel_id,
                    name=name,
                    description=char_data.get("description", ""),
                    appearance=char_data.get("appearance", ""),
                )
                db.add(character)
                print(f"[测试任务] 创建角色: {name}")
        
        db.commit()
        print(f"[测试任务] 完成！")
        
    except Exception as e:
        print(f"[测试任务] 异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
