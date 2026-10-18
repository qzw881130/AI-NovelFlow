"""Bilingual compiler-owned prose. Protocol tokens and authority stay untouched."""


def no_bound_subjects(language):
    if language == "zh":
        return "此片段没有绑定的具名视觉主体。"
    return "No named visual subjects are bound in this Clip."


def identity_definition(subject, name, number, marks, language):
    if number is None:
        if language == "zh":
            return (f"{subject} is {name}, 无独立身份参考图；"
                    + (f"以角色库已记录的稳定外貌特征为准：{marks}；" if marks else "")
                    + "不得从其他人物参考图借用面容；当前服装、姿势或站位以 Canonical 视觉状态为准。")
        return (f"{subject} is {name}, with no individual identity Picture in this Clip; "
                + (f"use the recorded stable features: {marks}; " if marks else "")
                + "do not borrow another Subject's face; Canonical visual states determine current costume, pose, and floor position.")
    if language == "zh":
        return (f"{subject} is {name}, 稳定身份仅绑定到 <Picture {number}>；"
                + (f"已记录的稳定外貌特征：{marks}；" if marks else "")
                + "身份参考不决定当前服装、姿势或站位。")
    return (f"{subject} is {name}, the existing character whose stable identity is bound exclusively to <Picture {number}>; "
            + (f"recorded stable features: {marks}; " if marks else "")
            + "the identity reference does not determine current costume, pose, or floor position.")


def retention_intro(continuation, language):
    if language == "zh":
        return ("经验证的 Previous AV 结尾决定当前人物、服装、姿势、站位和镜头上下文；"
                "保留共享开头，不重演已经完成的动作。后续动作和调度以 Canonical 视觉状态及过渡为准。"
                if continuation else "当前 Canonical 视觉状态决定服装、姿势、站位和动作；身份参考不得覆盖这些内容。")
    return ("The verified Previous AV ending owns the current bodies, clothing, poses, floor positions, and camera context; "
            "preserve its shared opening context without replaying completed actions. "
            "Canonical visual states and transitions own subsequent action and staging."
            if continuation else "The current Canonical visual state owns clothing, poses, floor positions, and action; identity references cannot override it.")


def reference_note(picture, kind, label, language):
    if language == "zh":
        notes = {
            "CHARACTER_IDENTITY": f"{picture} — CHARACTER_IDENTITY / {label}：仅用于稳定身份；不决定当前服装、姿势、站位或动作。",
            "SCENE": f"{picture} — SCENE / {label or '当前场景'}：仅用于环境外观；背景人物不构成新增 Subject。",
            "PROP": f"{picture} — PROP / {label or '既有道具'}：仅用于道具外观；放置及使用以 Canonical 状态为准。",
            "DIRECTOR_VISUAL_ANCHOR": f"{picture} — DIRECTOR_VISUAL_ANCHOR / {label}：提供选定视觉构图参考；动作和调度仍以 Canonical 为准。",
        }
    else:
        notes = {
            "CHARACTER_IDENTITY": f"{picture} — CHARACTER_IDENTITY for {label}: stable identity only; not current clothing, pose, blocking, or action.",
            "SCENE": f"{picture} — SCENE / {label or 'current scene'}: environment appearance only; incidental people are not additional Subjects.",
            "PROP": f"{picture} — PROP / {label or 'canonical prop'}: prop appearance only; Canonical state owns placement and use.",
            "DIRECTOR_VISUAL_ANCHOR": f"{picture} — DIRECTOR_VISUAL_ANCHOR / {label}: selected visual composition guidance; Canonical action and staging remain authoritative.",
        }
    return notes[kind]


def silent_note(continuation, language):
    if language == "zh":
        return ("本 Clip 没有 Canonical 台词。新增动作期间所有人物保持无对白：不得新增说话、旁白或额外人声。"
                "仅生成符合场景的环境声和动作拟音。"
                + ("保留经验证的 Previous AV 共享前缀及其原有音轨，不新增或重播台词。" if continuation else ""))
    return ("This Clip has no Canonical dialogue. All characters remain silent throughout "
            "the newly generated action: no speech, narration or additional vocalization. "
            "Only grounded ambience and action Foley may be generated."
            + (" Preserve the verified Previous AV shared prefix and its existing audio, "
               "without adding or replaying speech." if continuation else ""))


def summary(duration, continuation, language):
    if language == "zh":
        return (f"当前 Canonical Clip 的续接片段，时长 {duration:g} 秒，从经验证的 Previous AV 共享上下文开始。"
                if continuation else f"当前 Canonical Clip 的执行片段，时长 {duration:g} 秒。")
    return (f"A {duration:g}-second continuation of the current Canonical Clip, beginning with the verified Previous AV shared context."
            if continuation else f"A {duration:g}-second execution of the current Canonical Clip.")
