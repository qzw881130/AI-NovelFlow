"""Bounded #06/#09 graph proof built on the existing typed ComfyUI graph vocabulary."""
from copy import deepcopy
import json
from app.services.keyframe_reference_graph import _Graph, _PROMPT_FIELDS, _SIDE_EFFECTS, KeyframeGraphError, semantic_graph_digest
from app.services.comfyui.workflows import WorkflowBuilder


def inspect_graph(graph, mapping, reference_nodes, *, filenames=None, prompt=None):
    view = _Graph(graph)
    save, text_node = str(mapping["save_image_node_id"]),str(mapping["prompt_node_id"])
    if view.kind(save) != "SaveImage" or view.kind(text_node) not in _PROMPT_FIELDS:
        raise ValueError("RSA_MEDIA_MAPPING_INVALID")
    if len(reference_nodes) not in (1,2,3) or len(set(reference_nodes)) != len(reference_nodes):
        raise ValueError("RSA_MEDIA_REFERENCE_COUNT_INVALID")
    loads = {key for key in graph if view.kind(key)=="LoadImage"}
    if loads != set(reference_nodes):
        raise ValueError("RSA_MEDIA_EXTRA_OR_MISSING_REFERENCE")
    decode=view.source(save,"images",{"VAEDecode"})
    sampler=view.source(decode,"samples",{"SamplerCustomAdvanced","KSampler"})
    family="flux2" if view.kind(sampler)=="SamplerCustomAdvanced" else "qwen"
    guider=view.source(sampler,"guider",{"CFGGuider"}) if family=="flux2" else sampler
    routes=[]
    def image_source(node):
        route=[]
        while view.kind(node) in {"ImageScaleToTotalPixels","ImageResizeKJv2"}:
            route.append(node);node=view.edges[node]["image"][0]
        if view.kind(node)!="LoadImage" or node not in loads:
            raise ValueError("RSA_MEDIA_IMAGE_ROUTE_INVALID")
        routes.append([node,*reversed(route)])
        return node
    def conditioning(field):
        node=view.edges[guider][field][0];refs=[]
        while view.kind(node) in {"ReferenceLatent","ConditioningZeroOut"}:
            if view.kind(node)=="ReferenceLatent":
                vae=view.source(node,"latent",{"VAEEncode"})
                refs.append(image_source(view.edges[vae]["pixels"][0]))
            elif field=="positive":raise ValueError("RSA_MEDIA_POSITIVE_ERASED")
            node=view.edges[node]["conditioning"][0]
        if family=="flux2":
            if view.kind(node)!="CLIPTextEncode" or list(reversed(refs)) not in ([*reference_nodes],[] if field=="negative" else [*reference_nodes]):
                raise ValueError("RSA_MEDIA_REFERENCE_ORDER_CHANGED")
        else:
            if view.kind(node)!="TextEncodeQwenImageEditPlusAdvance_lrzjason":raise ValueError("RSA_MEDIA_ENCODER_UNSUPPORTED")
            refs=[image_source(view.edges[node][key][0]) for key in ("vl_resize_image1","vl_resize_image2","vl_resize_image3") if key in graph[node]["inputs"]]
            if refs!=reference_nodes:raise ValueError("RSA_MEDIA_REFERENCE_ORDER_CHANGED")
        return node
    positive,negative=conditioning("positive"),conditioning("negative")
    if family=="qwen":
        if positive!=negative:raise ValueError("RSA_MEDIA_NEGATIVE_ENCODER_CHANGED")
        latent=view.source(sampler,"latent_image",{"VAEEncode"})
        if image_source(view.edges[latent]["pixels"][0])!=reference_nodes[0]:raise ValueError("RSA_MEDIA_INITIALIZATION_CHANGED")
        seed_node,seed_field=sampler,"seed"
    else:
        latent=view.source(sampler,"latent_image",{"EmptyFlux2LatentImage"})
        if graph[latent]["inputs"]["batch_size"]!=1:raise ValueError("RSA_MEDIA_BATCH_SIZE_INVALID")
        seed_node,seed_field=view.source(sampler,"noise",{"RandomNoise"}),"noise_seed"
    text_cache={}
    def text_value(node,field):
        key=(node,field)
        if key in text_cache:return text_cache[key]
        value,count=read_text(node,field)
        if len(value)>65536 or count>1:raise ValueError('RSA_MEDIA_TEXT_BUDGET_OR_MULTIPLICITY')
        text_cache[key]=(value,count)
        return value,count
    def read_text(node,field):
        value=graph[node]["inputs"][field]
        if isinstance(value,str):return value,int(node==text_node and field==_PROMPT_FIELDS[view.kind(text_node)])
        parent=view.edges[node][field][0];kind=view.kind(parent)
        if kind in {"CR Text","CR Prompt Text"}:return text_value(parent,_PROMPT_FIELDS[kind])
        if kind=="ConcatTextOfUtils":
            if graph[parent]["inputs"]["separator"]!="":raise ValueError("RSA_MEDIA_TEXT_SEPARATOR_CHANGED")
            parts=[text_value(parent,key) for key in ("text1","text2","text3") if key in graph[parent]["inputs"]]
            return ''.join(p[0] for p in parts),sum(p[1] for p in parts)
        raise ValueError("RSA_MEDIA_TEXT_ROUTE_UNSUPPORTED")
    effective,count=text_value(positive,_PROMPT_FIELDS[view.kind(positive)])
    if count!=1:raise ValueError("RSA_MEDIA_PROMPT_NOT_BOUND_ONCE")
    if prompt is not None and graph[text_node]["inputs"][_PROMPT_FIELDS[view.kind(text_node)]]!=prompt:
        raise ValueError("RSA_MEDIA_PROMPT_CHANGED")
    for node in graph:
        kind=view.kind(node)
        if kind in {"SaveImage","VAEDecode","KSampler","SamplerCustomAdvanced"} and node not in {save,decode,sampler}:
            raise ValueError("RSA_MEDIA_UNRELATED_GENERATION_BRANCH")
        if kind=="GetImageSize":
            parent=view.edges[node]["image"][0]
            if parent!=decode:image_source(parent)
        if kind in _SIDE_EFFECTS:
            if kind=="ShowText|pysssss":
                if text_value(node,"text")!=(effective,1):raise ValueError("RSA_MEDIA_PREVIEW_TEXT_CHANGED")
            else:
                field="images" if kind=="PreviewImage" else "anything"
                parent=view.edges[node][field][0]
                if parent!=decode:image_source(parent)
    if filenames is not None:
        if len(filenames)!=len(reference_nodes) or any(graph[n]["inputs"]["image"]!=f for n,f in zip(reference_nodes,filenames)):
            raise ValueError("RSA_MEDIA_UPLOADED_FILENAME_CHANGED")
    return {"family":family,"save_image_node_id":save,"prompt_node_id":text_node,"reference_nodes":reference_nodes,
        "routes":routes,"seed_node":seed_node,"seed_field":seed_field,"effective_prompt":effective,
        "semantic_graph_hash":semantic_graph_digest(graph)}


def prepare_graph(workflow,mapping,reference_nodes,aspect_ratio,seed):
    graph=WorkflowBuilder().build_shot_workflow(prompt="",workflow_json=json.dumps(workflow),node_mapping=mapping,aspect_ratio=aspect_ratio,style="")
    proof=inspect_graph(graph,mapping,reference_nodes)
    graph[proof['seed_node']]['inputs'][proof['seed_field']]=seed
    return graph
