"""Fail-closed #09 graph proof and bounded, opt-in numeric graph identity.

No application imports, workflow loading, submission, or I/O belongs here. Build
once with an empty mapped prompt, prepare, then bind the prompt/upload receipt on
that same graph and validate again. Passing both expectations as None is strictly
structural preflight; final validation requires a nonblank exact prompt and, for
one reference, a nonblank exact upload filename. This is not a ComfyUI interpreter.
"""

from copy import deepcopy
import hashlib
import json
import math


class KeyframeGraphError(RuntimeError):
    """A bounded-profile failure that the submission boundary can wrap."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_MAPPING_KEYS = {
    "prompt_node_id", "save_image_node_id", "reference_image_node_id",
    "width_node_id", "height_node_id",
}
_PROMPT_FIELDS = {
    "CLIPTextEncode": "text",
    "CR Text": "text",
    "CR Prompt Text": "prompt",
    "TextEncodeQwenImageEditPlusAdvance_lrzjason": "prompt",
}
_QWEN = "TextEncodeQwenImageEditPlusAdvance_lrzjason"
_SIDE_EFFECTS = {"PreviewImage", "ShowText|pysssss", "LayerUtility: PurgeVRAM"}
_REFERENCE_NODES = {
    "ReferenceLatent", "LoadImage", "ImageScaleToTotalPixels", "VAEEncode",
    "PreviewImage", "LayerUtility: PurgeVRAM",
}

# Only these output slots and input ports have semantics in this proof. Lowercase
# types are literal widgets; STRING/INT additionally permit typed links. '?' marks
# an optional input, not a wildcard. In particular there is no ANY/media fallback.
_SPECS = {
    "SaveImage": ((), {"images": "IMAGE", "filename_prefix": "str"}),
    "PreviewImage": ((), {"images": "IMAGE"}),
    "LoadImage": (("IMAGE", "MASK"), {"image": "str", "upload?": "str"}),
    "VAEDecode": (("IMAGE",), {"samples": "LATENT", "vae": "VAE"}),
    "VAEEncode": (("LATENT",), {"pixels": "IMAGE", "vae": "VAE"}),
    "VAELoader": (("VAE",), {"vae_name": "str"}),
    "UNETLoader": (("MODEL",), {"unet_name": "str", "weight_dtype": "str"}),
    "CLIPLoader": (("CLIP",), {"clip_name": "str", "type": "str", "device?": "str"}),
    "LoraLoaderModelOnly": (("MODEL",), {
        "model": "MODEL", "lora_name": "str", "strength_model": "number",
    }),
    "ModelSamplingAuraFlow": (("MODEL",), {"model": "MODEL", "shift": "number"}),
    "CFGNorm": (("MODEL",), {"model": "MODEL", "strength": "number", "pre_cfg": "bool"}),
    "KSamplerSelect": (("SAMPLER",), {"sampler_name": "str"}),
    "RandomNoise": (("NOISE",), {"noise_seed": "int"}),
    "SamplerCustomAdvanced": (("LATENT", "LATENT"), {
        "noise": "NOISE", "guider": "GUIDER", "sampler": "SAMPLER",
        "sigmas": "SIGMAS", "latent_image": "LATENT",
    }),
    "KSampler": (("LATENT",), {
        "seed": "int", "steps": "int", "cfg": "number", "sampler_name": "str",
        "scheduler": "str", "denoise": "number", "model": "MODEL",
        "positive": "CONDITIONING", "negative": "CONDITIONING", "latent_image": "LATENT",
    }),
    "CFGGuider": (("GUIDER",), {
        "cfg": "number", "model": "MODEL", "positive": "CONDITIONING", "negative": "CONDITIONING",
    }),
    "Flux2Scheduler": (("SIGMAS",), {"steps": "int", "width": "INT", "height": "INT"}),
    "EmptyFlux2LatentImage": (("LATENT",), {"width": "INT", "height": "INT", "batch_size": "int"}),
    "ImageScaleToTotalPixels": (("IMAGE",), {
        "image": "IMAGE", "upscale_method": "str", "megapixels": "number", "resolution_steps?": "int",
    }),
    "ImageResizeKJv2": (("IMAGE",), {
        "image": "IMAGE", "width": "INT", "height": "INT", "upscale_method": "str",
        "keep_proportion": "str", "pad_color": "str", "crop_position": "str",
        "divisible_by": "int", "device": "str",
    }),
    "GetImageSize": (("INT", "INT"), {"image": "IMAGE"}),
    "easy int": (("INT",), {"value": "INT"}),
    "CLIPTextEncode": (("CONDITIONING",), {"text": "STRING", "clip": "CLIP"}),
    "ConditioningZeroOut": (("CONDITIONING",), {"conditioning": "CONDITIONING"}),
    "ReferenceLatent": (("CONDITIONING",), {"conditioning": "CONDITIONING", "latent": "LATENT"}),
    "CR Text": (("STRING",), {"text": "STRING"}),
    "CR Prompt Text": (("STRING",), {"prompt": "STRING"}),
    "ConcatTextOfUtils": (("STRING",), {
        "text1": "STRING", "text2": "STRING", "text3?": "STRING", "separator": "str",
    }),
    "ShowText|pysssss": ((), {"text": "STRING", "text_0?": "str"}),
    "LayerUtility: PurgeVRAM": ((), {"anything": "IMAGE", "purge_cache": "bool", "purge_models": "bool"}),
    _QWEN: (("CONDITIONING",), {
        "prompt": "STRING", "target_size": "int", "target_vl_size": "int",
        "upscale_method": "str", "crop_method": "str", "instruction": "str",
        "clip": "CLIP", "vae": "VAE", "vl_resize_image1": "IMAGE",
        "vl_resize_image2?": "IMAGE", "vl_resize_image3?": "IMAGE",
    }),
}


def normalize_keyframe_mapping(mapping) -> dict:
    """Normalize canonical mapping IDs, never infer roles or alias #06 slots.

    Prompt/save are required. Reference/width/height may be absent, null or empty.
    Nonnegative integers become strings; booleans, auto, aliases, duplicate roles,
    unknown keys (including load_image_node_id) and role-specific slots fail.
    """
    if not isinstance(mapping, dict) or any(key not in _MAPPING_KEYS for key in mapping):
        raise KeyframeGraphError("invalid_mapping", "Only canonical #09 node mapping keys are supported")
    result = {}
    for key, value in mapping.items():
        if value is None or value == "":
            continue
        if type(value) is int and value >= 0:
            value = str(value)
        if (not isinstance(value, str) or not value.strip() or value != value.strip()
                or value.lower() in {"auto", "none", "null"}):
            raise KeyframeGraphError("invalid_mapping", f"{key} must be an explicit node ID")
        result[key] = value
    if not {"prompt_node_id", "save_image_node_id"} <= result.keys():
        raise KeyframeGraphError("invalid_mapping", "Explicit prompt_node_id and save_image_node_id are required")
    if len(set(result.values())) != len(result):
        raise KeyframeGraphError("invalid_mapping", "Different mapping roles cannot alias the same node")
    return result


class _Graph:
    """Typed edges shared by proof and preparation, with no graph mutation."""

    def __init__(self, graph):
        if not isinstance(graph, dict) or not graph or len(graph) > 256:
            raise KeyframeGraphError("invalid_graph", "Expected a nonempty API graph of at most 256 nodes")
        self.nodes = graph
        self.edges = {}
        for node_id, node in graph.items():
            if (not isinstance(node_id, str) or not node_id or not isinstance(node, dict)
                    or set(node) - {"inputs", "class_type", "_meta"}
                    or not isinstance(node.get("inputs"), dict)):
                raise KeyframeGraphError("invalid_graph", f"Malformed API node {node_id!r}")
            kind = node.get("class_type")
            if not isinstance(kind, str) or kind not in _SPECS:
                raise KeyframeGraphError("unsupported_node", f"Unsupported class at node {node_id}: {kind!r}")
            self.edges[node_id] = {}

        for node_id, node in graph.items():
            fields = _SPECS[node["class_type"]][1]
            allowed = {key.rstrip("?"): value for key, value in fields.items()}
            required = {key for key in fields if not key.endswith("?")}
            if set(node["inputs"]) - allowed.keys() or not required <= node["inputs"].keys():
                raise KeyframeGraphError("unsupported_port", f"Unknown or missing input at node {node_id}")
            for field, value in node["inputs"].items():
                expected = allowed[field]
                if isinstance(value, list):
                    if (expected.islower() or len(value) != 2 or not isinstance(value[0], str)
                            or value[0] not in graph or type(value[1]) is not int or value[1] < 0):
                        raise KeyframeGraphError("invalid_link", f"Invalid link at {node_id}.{field}")
                    outputs = _SPECS[graph[value[0]]["class_type"]][0]
                    if value[1] >= len(outputs) or outputs[value[1]] != expected:
                        raise KeyframeGraphError("invalid_link", f"Wrong source output type/slot at {node_id}.{field}")
                    self.edges[node_id][field] = (value[0], value[1])
                else:
                    valid = (
                        (expected in {"str", "STRING"} and isinstance(value, str))
                        or (expected in {"int", "INT"} and type(value) is int)
                        or (expected == "bool" and type(value) is bool)
                        or (expected == "number" and type(value) in {int, float}
                            and (type(value) is int or math.isfinite(value)))
                    )
                    if not valid:
                        raise KeyframeGraphError("invalid_input", f"Expected {expected} at {node_id}.{field}")

        visiting, visited = set(), set()

        def visit(node_id):
            if node_id in visiting:
                raise KeyframeGraphError("invalid_graph", f"Cycle at node {node_id}")
            if node_id in visited:
                return
            visiting.add(node_id)
            for source, _ in self.edges[node_id].values():
                visit(source)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in graph:
            visit(node_id)

    def kind(self, node_id):
        return self.nodes[node_id]["class_type"]

    def source(self, node_id, field, kinds):
        link = self.edges[node_id].get(field)
        if link is None or self.kind(link[0]) not in kinds:
            raise KeyframeGraphError("unsupported_topology", f"Unsupported source at {node_id}.{field}")
        return link[0]

    def ancestors(self, roots):
        seen, pending = set(), list(roots)
        while pending:
            node_id = pending.pop()
            if node_id not in seen:
                seen.add(node_id)
                pending.extend(source for source, _ in self.edges[node_id].values())
        return seen


def validate_keyframe_graph(
    graph, mapping, *, reference_count: int,
    expected_filename: str | None = None, expected_prompt: str | None = None,
) -> dict:
    """Prove the mapped generated output and return JSON-safe task metadata.

    positive_consumer_node_id is the positive text encoder, not the guider.
    image_source_nodes contains distinct LoadImage IDs, never generated images.
    image_routes records source-to-consumer node IDs, including approved previews
    and cleanup sinks; the kind distinguishes reference from generated routes.
    A removed reference mapping may remain in a prepared zero-reference graph.
    """
    if type(reference_count) is not int or reference_count not in (0, 1):
        raise KeyframeGraphError("reference_count", "#09 supports exactly zero or one reference")
    mapping = normalize_keyframe_mapping(mapping)
    view = _Graph(graph)
    save_id, prompt_id = mapping["save_image_node_id"], mapping["prompt_node_id"]
    if save_id not in graph or view.kind(save_id) != "SaveImage":
        raise KeyframeGraphError("invalid_mapping", "save_image_node_id must identify SaveImage")
    if prompt_id not in graph or view.kind(prompt_id) not in _PROMPT_FIELDS:
        raise KeyframeGraphError("invalid_mapping", "prompt_node_id must identify a known prompt input")
    prompt_field = _PROMPT_FIELDS[view.kind(prompt_id)]
    if not isinstance(graph[prompt_id]["inputs"][prompt_field], str):
        raise KeyframeGraphError("prompt_binding", "Mapped prompt input must be a literal writable string")

    decode_id = view.source(save_id, "images", {"VAEDecode"})
    sampler_id = view.source(decode_id, "samples", {"SamplerCustomAdvanced", "KSampler"})
    family = "flux2" if view.kind(sampler_id) == "SamplerCustomAdvanced" else "qwen"
    guider_id = view.source(sampler_id, "guider", {"CFGGuider"}) if family == "flux2" else sampler_id
    latent_id = view.source(sampler_id, "latent_image", {"EmptyFlux2LatentImage"} if family == "flux2" else {"VAEEncode"})
    if family == "flux2" and graph[latent_id]["inputs"]["batch_size"] != 1:
        raise KeyframeGraphError("unsupported_topology", "Only batch_size=1 is supported")
    if family == "qwen" and reference_count == 0:
        raise KeyframeGraphError("unsupported_none", "Qwen image conditioning and VAE initialization require a reference")

    routes = []

    def image_path(node_id, *, generated=False):
        path = []
        image_types = {"ImageScaleToTotalPixels"} if family == "flux2" else {"ImageResizeKJv2"}
        while view.kind(node_id) in image_types:
            path.append(node_id)
            node_id = view.source(node_id, "image", image_types | {"LoadImage", "VAEDecode"})
        if view.kind(node_id) == "LoadImage":
            kind = "reference"
        elif generated and node_id == decode_id:
            kind = "generated"
        else:
            raise KeyframeGraphError("reference_binding", "Image route is not the approved reference/generated output")
        return kind, node_id, [node_id, *reversed(path)]

    def add_route(role, consumer_id, field, image_id, via=(), *, generated=False):
        kind, source_id, path = image_path(image_id, generated=generated)
        routes.append({
            "role": role, "kind": kind, "source_node_id": source_id,
            "consumer_node_id": consumer_id, "consumer_field": field,
            "node_ids": [*path, *via, consumer_id],
        })

    def conditioning(field):
        node_id = view.edges[guider_id][field][0]
        additions = 0
        while view.kind(node_id) in {"ReferenceLatent", "ConditioningZeroOut"}:
            if view.kind(node_id) == "ConditioningZeroOut":
                if field == "positive":
                    raise KeyframeGraphError("prompt_binding", "Positive prompt is erased by ConditioningZeroOut")
            else:
                additions += 1
                if family != "flux2" or additions > 1:
                    raise KeyframeGraphError("reference_count", "Multiple/unsupported reference conditioning additions")
                vae_id = view.source(node_id, "latent", {"VAEEncode"})
                add_route(field, node_id, "latent", view.edges[vae_id]["pixels"][0], (vae_id,))
            node_id = view.edges[node_id]["conditioning"][0]
        if view.kind(node_id) != ("CLIPTextEncode" if family == "flux2" else _QWEN):
            raise KeyframeGraphError("unsupported_topology", "Unsupported effective conditioning encoder")
        if family == "flux2" and (additions != reference_count if field == "positive" else additions > reference_count):
            raise KeyframeGraphError("reference_count", "Reference must be bound on the effective positive conditioning")
        if family == "qwen":
            images = [key for key in graph[node_id]["inputs"] if key in {
                "vl_resize_image1", "vl_resize_image2", "vl_resize_image3",
            }]
            if len(images) != 1:
                raise KeyframeGraphError("reference_count", "Qwen must have exactly one image slot, even for the same source")
            add_route(field, node_id, images[0], view.edges[node_id][images[0]][0])
        return node_id

    positive_id = conditioning("positive")
    negative_id = conditioning("negative")
    if family == "qwen":
        if negative_id != positive_id:
            raise KeyframeGraphError("unsupported_topology", "Only the known shared Qwen positive/zeroed-negative encoder is supported")
        add_route("initialization", sampler_id, "latent_image", view.edges[latent_id]["pixels"][0], (latent_id,))

    text_evidence = {}

    def text_identity(node_id, field):
        key = (node_id, field)
        if key in text_evidence:
            return text_evidence[key]
        value = graph[node_id]["inputs"][field]
        if isinstance(value, str):
            mapped = key == (prompt_id, prompt_field)
            evidence = (int(mapped), not mapped and value != "")
        else:
            source_id = view.edges[node_id][field][0]
            kind = view.kind(source_id)
            if kind in {"CR Text", "CR Prompt Text"}:
                evidence = text_identity(source_id, _PROMPT_FIELDS[kind])
            elif kind == "ConcatTextOfUtils" and family == "qwen":
                if graph[source_id]["inputs"]["separator"] != "":
                    raise KeyframeGraphError("prompt_binding", "Concat separator must be exactly empty")
                parts = [text_identity(source_id, part) for part in ("text1", "text2", "text3")
                         if part in graph[source_id]["inputs"]]
                # Saturated multiplicity plus memoization avoids expanding a shared
                # concat DAG, including when every literal (and prompt) is empty.
                evidence = (min(2, sum(count for count, _ in parts)), any(extra for _, extra in parts))
            else:
                raise KeyframeGraphError("prompt_binding", "Only known identity text sources are supported")
        text_evidence[key] = evidence
        return evidence

    def bound_prompt(node_id, field):
        if text_identity(node_id, field) != (1, False):
            raise KeyframeGraphError("prompt_binding", "Effective positive text must be the mapped prompt exactly once, with empty other strings")
        return graph[prompt_id]["inputs"][prompt_field]

    effective_prompt = bound_prompt(positive_id, _PROMPT_FIELDS[view.kind(positive_id)])
    core = view.ancestors([save_id])
    for node_id in sorted(graph):
        if view.kind(node_id) == "GetImageSize":
            add_route("dimensions", node_id, "image", view.edges[node_id]["image"][0], generated=node_id not in core)
    roots = [save_id]
    for node_id in sorted(graph):
        kind = view.kind(node_id)
        if kind in {"SaveImage", "VAEDecode", "KSampler", "SamplerCustomAdvanced"} and node_id not in {save_id, decode_id, sampler_id}:
            raise KeyframeGraphError("unrelated_branch", "Only the mapped SaveImage/decode/sampler generation branch is supported")
        if kind in _SIDE_EFFECTS:
            roots.append(node_id)
            if kind == "ShowText|pysssss":
                bound_prompt(node_id, "text")
            else:
                field = "images" if kind == "PreviewImage" else "anything"
                add_route("preview" if kind == "PreviewImage" else "cleanup", node_id, field,
                          view.edges[node_id][field][0], generated=True)

    sources = sorted(node_id for node_id in graph if view.kind(node_id) == "LoadImage")
    reference_id = mapping.get("reference_image_node_id") if reference_count else None
    route_sources = {route["source_node_id"] for route in routes if route["kind"] == "reference"}
    if len(sources) != reference_count or set(sources) != route_sources:
        raise KeyframeGraphError("reference_count", "Extra, orphan, or missing image source")
    if reference_count and sources != [reference_id]:
        raise KeyframeGraphError("reference_binding", "Generic reference_image_node_id must identify the effective LoadImage")
    if not reference_count and mapping.get("reference_image_node_id") in graph:
        raise KeyframeGraphError("reference_binding", "Zero-reference mapping must not alias a surviving node")
    if view.ancestors(roots) != set(graph):
        raise KeyframeGraphError("unrelated_branch", "Graph contains nodes outside the approved generation/helper branches")
    for axis in ("width", "height"):
        key = f"{axis}_node_id"
        if key not in mapping:
            continue
        dimension_nodes = set()
        for node_id in core:
            if view.kind(node_id) not in {"EmptyFlux2LatentImage", "Flux2Scheduler", "ImageResizeKJv2"}:
                continue
            link = view.edges[node_id].get(axis)
            while link and view.kind(link[0]) == "easy int":
                dimension_nodes.add(link[0])
                link = view.edges[link[0]].get("value")
        if mapping[key] not in dimension_nodes:
            raise KeyframeGraphError("invalid_mapping", f"{key} must identify an effective easy int {axis} input")

    filename = graph[reference_id]["inputs"]["image"] if reference_id else None
    if expected_filename is not None or expected_prompt is not None:
        if not isinstance(expected_prompt, str) or not expected_prompt.strip():
            raise KeyframeGraphError("prompt_binding", "Final proof requires a nonblank exact prompt")
        if effective_prompt != expected_prompt:
            raise KeyframeGraphError("prompt_binding", "Effective positive prompt differs from the exact expected prompt")
        if reference_count:
            if not isinstance(expected_filename, str) or not expected_filename.strip() or filename != expected_filename:
                raise KeyframeGraphError("reference_binding", "Effective image differs from the exact upload receipt")
        elif expected_filename is not None:
            raise KeyframeGraphError("reference_binding", "Zero-reference proof cannot bind an upload filename")

    return {
        "family": family, "reference_count": reference_count, "reference_node_id": reference_id,
        "reference_filename": filename, "prompt_node_id": prompt_id, "prompt_field": prompt_field,
        "effective_prompt": effective_prompt, "save_image_node_id": save_id,
        "decode_node_id": decode_id, "sampler_node_id": sampler_id,
        "positive_consumer_node_id": positive_id,
        "image_source_nodes": sources,
        "image_routes": sorted(routes, key=lambda route: (route["role"], route["consumer_node_id"], route["consumer_field"])),
    }


def prepare_keyframe_graph(graph, mapping, *, has_reference: bool) -> dict:
    """Deep-copy and preflight; only safely detach the known Flux reference path.

    Validation happens before pruning, so orphan/default sources and unknown
    branches cannot be laundered into an acceptable graph. Image-derived dimensions
    and Qwen VAE initialization are never replaced with guessed dimensions/latents.
    """
    if type(has_reference) is not bool:
        raise KeyframeGraphError("reference_count", "has_reference must be a boolean")
    view = _Graph(graph)
    count = sum(view.kind(node_id) == "LoadImage" for node_id in graph)
    inspection = validate_keyframe_graph(graph, mapping, reference_count=1 if has_reference else count)
    prepared = deepcopy(graph)
    if has_reference or count == 0:
        return prepared
    if inspection["family"] != "flux2" or any(route["role"] in {"dimensions", "initialization"} for route in inspection["image_routes"]):
        raise KeyframeGraphError("unsupported_none", "This image-dependent topology cannot be prepared without a reference")

    remove = set()
    for route in inspection["image_routes"]:
        if route["kind"] == "reference":
            remove.update(node_id for node_id in route["node_ids"] if view.kind(node_id) in _REFERENCE_NODES)
    bypass = {node_id: graph[node_id]["inputs"]["conditioning"]
              for node_id in remove if view.kind(node_id) == "ReferenceLatent"}
    for node_id, node in prepared.items():
        if node_id not in remove:
            for field, (source_id, _) in view.edges[node_id].items():
                if source_id in bypass:
                    node["inputs"][field] = deepcopy(bypass[source_id])
    for node_id in remove:
        del prepared[node_id]
    validate_keyframe_graph(prepared, mapping, reference_count=0)
    return prepared


def stable_graph_fingerprint(graph, mapping) -> str:
    """SHA-256 of a proved graph/mapping, excluding only task-volatile fields.

    Ignores node _meta, RandomNoise.noise_seed, KSampler.seed, SaveImage's prefix,
    the mapped literal prompt and mapped LoadImage filename. Model names, cfg,
    dimensions, Qwen instruction/context, other text and all topology remain.
    This is a cache identity, not a replacement for final binding validation.
    """
    mapping = normalize_keyframe_mapping(mapping)
    view = _Graph(graph)
    count = sum(view.kind(node_id) == "LoadImage" for node_id in graph)
    inspection = validate_keyframe_graph(graph, mapping, reference_count=count)
    stable = deepcopy(graph)
    for node in stable.values():
        node.pop("_meta", None)
        volatile = {"RandomNoise": "noise_seed", "KSampler": "seed", "SaveImage": "filename_prefix"}.get(node["class_type"])
        if volatile:
            node["inputs"].pop(volatile, None)
    stable[inspection["prompt_node_id"]]["inputs"].pop(inspection["prompt_field"])
    if inspection["reference_node_id"]:
        stable[inspection["reference_node_id"]]["inputs"].pop("image")
    encoded = json.dumps({"graph": stable, "mapping": mapping}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# History-only opt-in, confirmed by Batch1 V017 and object_info on 2026-09-08.
# Entries are (minimum, maximum, optional (selector field, exact choice)). These
# FLOAT ports do not extend _SPECS or the #09 validation/preparation profile.
H3_NUMBER_PORTS = {
    "VHS_VideoCombine": {"frame_rate": (1, None, None)},
    "MiniMaxH3DualClockSamplerT8": {
        "shift_video": (0.01, 100, None), "shift_audio": (0.01, 100, None),
    },
    "MiniMaxH3AudioConditioningT8": {"audio_denoise_strength": (0, 1, None)},
    "CreateVideo": {"fps": (1, 120, None)},
    "RTXVideoSuperResolution": {"resize_type.scale": (1, 4, ("resize_type", "scale by multiplier"))},
}


def _numeric_graph(graph, *, extra_number_ports=None):
    """Copy an API graph, folding only declared literal number widgets.

    Unknown classes/ports, metadata, integer widgets and links remain exact.
    Integral floats outside the JSON safe-integer range and negative zero stay
    exact: their workflow equivalence is unproved. No integer becomes float.
    This shared primitive does not impose #09's ports/topology/reference profile.
    """
    if not isinstance(graph, dict) or not graph or len(graph) > 256:
        raise KeyframeGraphError("invalid_graph", "Expected a nonempty API graph of at most 256 nodes")
    for node_id, node in graph.items():
        if (not isinstance(node_id, str) or not node_id or not isinstance(node, dict)
                or not isinstance(node.get("class_type"), str) or not node["class_type"]
                or not isinstance(node.get("inputs"), dict)):
            raise KeyframeGraphError("invalid_graph", f"Malformed API node {node_id!r}")
    try:
        json.dumps(graph, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise KeyframeGraphError("invalid_graph", "Graph must contain finite JSON values") from exc
    pending = [graph]
    while pending:
        value = pending.pop()
        if type(value) is dict and all(type(key) is str for key in value):
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)
        elif type(value) not in {str, int, float, bool, type(None)}:
            raise KeyframeGraphError("invalid_graph", "Only exact JSON containers, string keys and scalar types are supported")
    normalized = deepcopy(graph)
    for node_id, node in normalized.items():
        declared = {field.rstrip("?"): kind for field, kind in _SPECS.get(node["class_type"], ((), {}))[1].items()}
        fields = {field: (None, None, None) for field, kind in declared.items() if kind == "number"}
        for field, bounds in (extra_number_ports or {}).get(node["class_type"], {}).items():
            if field in declared:
                raise KeyframeGraphError("invalid_profile", "Extra numeric ports cannot override the declared #09 ports")
            selector = bounds[2]
            if selector is None or node["inputs"].get(selector[0]) == selector[1]:
                fields[field] = bounds
        for field, (minimum, maximum, _) in fields.items():
            if field not in node["inputs"]:
                continue
            value = node["inputs"][field]
            if (field not in declared and type(value) is list and len(value) == 2
                    and type(value[0]) is str and value[0] in graph and type(value[1]) is int and value[1] >= 0):
                continue  # A typed link is preserved, never traversed or numerically folded.
            if type(value) not in {int, float} or (type(value) is float and not math.isfinite(value)):
                raise KeyframeGraphError("invalid_input", f"Expected number at {node_id}.{field}")
            if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
                raise KeyframeGraphError("invalid_input", f"Number outside reviewed bounds at {node_id}.{field}")
            if (type(value) is float and value.is_integer()
                    and abs(value) <= 2**53 - 1
                    and not (value == 0 and math.copysign(1, value) < 0)):
                node["inputs"][field] = int(value)
    return normalized


def numeric_graph_digest(graph, *, extra_number_ports=None) -> str:
    """Full API graph identity, not a storage seal or a topology/binding proof.

    Only reviewed numeric widget spelling is canonicalized. Unknown node/port
    values, metadata, seeds, filenames, list order and connections remain exact.
    extra_number_ports is a trusted code-defined opt-in, never graph/task input;
    H3_NUMBER_PORTS adds only the six schema-confirmed H3 FLOAT literals. Default
    #06/#09 callers retain their original numeric port set and typed profile.
    """
    try:
        encoded = json.dumps(_numeric_graph(graph, extra_number_ports=extra_number_ports), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise KeyframeGraphError("invalid_graph", "Graph must contain finite JSON values") from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def semantic_graph_digest(graph) -> str:
    """#09 full graph identity; validate its original typed inputs before folding."""
    _Graph(graph)
    return numeric_graph_digest(graph)


def semantic_stable_graph_fingerprint(graph, mapping) -> str:
    """Derived cache identity; the persisted v1 stable fingerprint is unchanged."""
    _Graph(graph)
    return stable_graph_fingerprint(_numeric_graph(graph), mapping)
