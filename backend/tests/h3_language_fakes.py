"""Deterministic translation fixtures, never a runtime translation fallback."""
from copy import deepcopy

ENGLISH = {
    '纤细身形、榛褐色下垂眼、右耳前小痣和低位束发': 'A slender build, downturned hazel-brown eyes, a small mole in front of the right ear and hair tied low',
    '长方脸、左眉断眉、鼻梁淡雀斑和右分黑褐短发': 'A rectangular face, a gap in the left eyebrow, faint freckles on the nose bridge and short black-brown hair parted on the right',
    '瘦长体态、浅褐色大单眼皮眼、左下颌小黑痣和耳下亚麻棕发': 'A tall lean build, large light-brown monolid eyes, a small dark mole on the left jaw and flaxen-brown hair below the ears',
    '宽肩方脸、右眉尾旧疤、下巴浅凹和深褐色内双眼': 'Broad shoulders, a square face, an old scar at the outer end of the right eyebrow, a shallow chin cleft and dark-brown hooded eyes',
    '浅蓝灰色微垂眼、左眼下褐痣、后移发际线、银灰短须和略丰腴体态': 'Pale blue-gray slightly downturned eyes, a brown mole beneath the left eye, a receding hairline, a short silver-gray beard and a slightly plump build',
    '清瘦长脸、深蓝灰色狭长眼、右太阳穴浅褐斑和短山羊胡': 'A lean long face, narrow dark blue-gray eyes, a light brown mark on the right temple and a short goatee',
    '高瘦轮廓、右鼻翼旁褐痣、灰绿色上挑眼和整齐小胡子': 'A tall slim build, a brown mole beside the right nostril, upturned gray-green eyes and a neat mustache',
    '稍矮敦实的轮廓、琥珀褐色圆杏眼、左嘴角下方黑痣和左分短卷发': 'A shorter stocky build, rounded almond-shaped amber-brown eyes, a dark mole below the left corner of the mouth and short curls parted on the left',
    '圆脸、暖褐圆眼、鼻梁右侧三颗雀斑和短刘海': 'A round face, round warm-brown eyes, three freckles on the right side of the bridge of the nose and short bangs',
    '王宫大厅': 'Royal palace hall', '王宫织造室': 'Royal weaving room',
    '王宫大门': 'Royal palace gate', '脚踏织机': 'Treadle loom',
    '王宫宫门': 'Royal palace gate', '王宫更衣室': 'Royal dressing room',
    '巨大镜子': 'Large mirror', '宫廷腰带': 'Court belt', '紫色长袍': 'Purple robe',
    '织造室灯': 'Weaving room lamp', '高背宝座': 'High-backed throne',
    '宽边礼帽': 'Wide-brimmed formal hat', '骗子木箱': 'Wooden chest',
}


def language_response(payload, original):
    """Synthetic directing prose for structural tests, not a quality evaluation."""
    response = deepcopy(original)
    language = payload.get('video_prompt_language')
    if language is None:
        return response
    sources = payload['compiler_description_sources']
    response['localized_descriptions'] = {
        key: (ENGLISH[value] if language == 'en' else value) for key, value in sources.items()}
    slots = ''.join(f"[[{event['slot']}]]" for event in payload['speech_slots'])
    response['detailed_description'] = (
        '<Subject 1> continues the authorized action, preserving the established camera and staging. '
        if language == 'en' else '<Subject 1>继续已授权动作，保持既有镜头和站位。') + slots
    response['overall_soundscape'] = ('Grounded ambience and action Foley only.' if language == 'en' else '仅保留有依据的环境声和动作拟音。')
    return response
