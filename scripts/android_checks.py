"""Pure assertions shared by Android automation and regression tests."""
import re
import xml.etree.ElementTree as ET

PACKAGE = "com.ggufchat.app"
PICKERS = {"com.android.documentsui", "com.google.android.documentsui"}


def nodes(xml):
    return list(ET.fromstring(xml).iter("node"))


def has_package(xml, packages):
    return any(n.get("package") in packages for n in nodes(xml))


def position(xml, *, text=None, desc=None, package=None, contains=False, class_name=None, resource_id=None):
    for node in nodes(xml):
        if node.get("enabled") != "true":
            continue
        if package and node.get("package") not in package:
            continue
        if class_name and node.get("class") != class_name:
            continue
        if resource_id and node.get("resource-id") != resource_id:
            continue
        if text is not None:
            value = node.get("text", "").casefold()
            if (text.casefold() not in value) if contains else (text.casefold() != value):
                continue
        if desc is not None and node.get("content-desc", "").casefold() != desc.casefold():
            continue
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
        if not match:
            continue
        x1, y1, x2, y2 = map(int, match.groups())
        if x2 > x1 and y2 > y1:
            return (x1 + x2) // 2, (y1 + y2) // 2
    return None


def imported(models, filename):
    if not isinstance(models, list):
        raise AssertionError("models.json não é uma lista")
    found = [m for m in models if m.get("fileName") == filename]
    if len(found) != 1 or not found[0].get("path") or not found[0].get("id"):
        raise AssertionError(f"Importação não confirmada ou duplicada: {filename}")
    return found[0]


def fusion(models, vision_name, projector_name):
    vision, projector = imported(models, vision_name), imported(models, projector_name)
    if vision["id"] == projector["id"] or vision.get("mmprojPath") != projector["path"]:
        raise AssertionError("Modelo de visão não está vinculado ao projetor esperado")
    if vision.get("multimodal") is not True:
        raise AssertionError("multimodal não foi persistido")
    return vision["id"], vision["path"], vision["mmprojPath"]


def assistant_reply(chats, chat_id, prompt):
    if not isinstance(chats, list):
        raise AssertionError("chats.json não é uma lista")
    chat = next((c for c in chats if c.get("id") == chat_id), None)
    if not chat or not chat.get("modelPath"):
        raise AssertionError("Conversa/modelo ausente")
    messages = chat.get("messages", [])
    users = [i for i, m in enumerate(messages) if m.get("role") == "user" and m.get("content") == prompt]
    if not users:
        raise AssertionError("O prompt não chegou à conversa esperada")
    replies = [m.get("content", "").strip() for m in messages[users[-1] + 1:]
               if m.get("role") == "assistant"]
    if not replies or not replies[-1]:
        raise AssertionError("Nenhuma resposta de assistant persistida após o prompt")
    return replies[-1]


def generation_completed(log):
    if "GGUF_REPAIR_GENERATION_FAILED" in log or re.search(r"FATAL EXCEPTION|Fatal signal|SIGSEGV", log):
        raise AssertionError("Falha ou crash durante a geração")
    return "GGUF_REPAIR_GENERATION_OK" in log


STATS_RE = re.compile(
    r'GGUF_GENERATION_STATS tokens=(\d+) decode_ns=(\d+) prefill_ns=(\d+) tokens_s=([\d.]+) '
    r'first_token_ns=(-?\d+) prompt_tokens=(\d+) reused_tokens=(\d+) completed=(\d)')
UI_FIRST_RE = re.compile(r'GGUF_UI_FIRST_TEXT send_to_first_ui_ns=(\d+)')
SOFTWARE_VULKAN_RE = re.compile(
    r'GGUF_VULKAN_SOFTWARE_DEVICE description="([^"]*)" action=cpu_fallback')


def generation_stats(log):
    """Native token counters of the last completed generation in `log`.

    tokens/decode_ns come from the native engine; `tokens_s` is recomputed here
    from those two integers so a formatted log line can never inflate a claim.
    """
    found = STATS_RE.findall(log)
    if not found:
        return None
    tokens, decode_ns, prefill_ns, _printed, first_ns, prompt, reused, completed = found[-1]
    tokens, decode_ns, prefill_ns = int(tokens), int(decode_ns), int(prefill_ns)
    first_ns, prompt, reused = int(first_ns), int(prompt), int(reused)
    return {
        'tokens': tokens,
        'decode_s': decode_ns / 1e9 if decode_ns else 0.0,
        'prefill_s': prefill_ns / 1e9 if prefill_ns else 0.0,
        'tokens_s': tokens / (decode_ns / 1e9) if tokens and decode_ns else 0.0,
        'first_token_s': first_ns / 1e9 if first_ns >= 0 else None,
        'prompt_tokens': prompt,
        'reused_tokens': reused,
        'completed': completed == '1',
    }


def ui_first_text_s(log):
    """Tap-to-visible-text wait measured on the Android main thread."""
    found = UI_FIRST_RE.findall(log)
    return int(found[-1]) / 1e9 if found else None


def software_vulkan_refused(log):
    """The device offered a software rasteriser as Vulkan and the app used the CPU."""
    found = SOFTWARE_VULKAN_RE.findall(log)
    return found[-1] if found else None


def gpu_offloaded(log):
    # Merely loading libggml-vulkan.so/SwiftShader is NOT proof of GPU inference.
    return bool(re.search(r"offloaded\s+[1-9]\d*(?:/\d+)?\s+layers?\s+to\s+GPU", log, re.I))


def basic_response_quality(greeting, arithmetic):
    """Conservative sanity check for the suite's two fixed prompts, not a benchmark."""
    if not re.search(r'\b(hello|hi|hey|greetings|good morning|good afternoon|good evening)\b', greeting, re.I):
        raise AssertionError('Resposta não contém uma saudação pertinente ao primeiro pedido')
    answer = arithmetic.casefold().replace('*', '').replace('`', '').strip(' \n.!')
    accepted = {'4', 'four', '2+2=4', '2 + 2 = 4', 'two + two = four', 'two plus two is four',
                'two plus two equals four', 'two plus two is 4', 'two plus two equals 4',
                'the answer is 4', 'the answer is four'}
    if answer not in accepted:
        raise AssertionError('Resposta à pergunta 2 + 2 não corresponde à resposta simples esperada: 4')
    return True


def vulkan_offloaded(log):
    """Require initialized Vulkan plus actual positive layer offload, not availability."""
    initialized = re.search(r'registered backend Vulkan|ggml_vulkan: Found [1-9]', log, re.I)
    # A GPU load may fail during context creation, then EngineManager retries CPU.
    # Evidence from that abandoned attempt must not approve the CPU generation.
    loads = list(re.finditer(r'llama_model_loader: loaded meta data', log))
    current = log[loads[-1].start():] if loads else log
    counts = re.findall(r'offloaded\s+(\d+)(?:/\d+)?\s+layers?\s+to\s+GPU', current, re.I)
    return bool(initialized and counts and int(counts[-1]) > 0)


def image_prefill_records(log, images):
    """A source image can become several native vision crops/chunks.
    Keep the exact source-image count AND require positive evaluated tokens.
    """
    records = re.findall(r'GGUF_IMAGE_EVALUATED tokens=([1-9]\d*) backend=(\w+)', log)
    assert images > 0 and len(records) >= images, records
    counts = re.findall(r'GGUF_MEDIA_PREFILL images=(\d+) tokens=([1-9]\d*) positions=([1-9]\d*)', log)
    assert len(counts) == 1 and int(counts[0][0]) == images, counts
    return records


def select_exact_documents(d, names):
    """Use document selection icons, not long-press range/exclusive selection."""
    import xml.etree.ElementTree as ET
    assert names and len(set(names)) == len(names)
    def rows():
        xml=d.ui();root=ET.fromstring(xml)
        parents={child:parent for parent in root.iter() for child in parent}
        found={}
        for node in root.iter('node'):
            name=node.get('text')
            if name not in names or node.get('package') not in PICKERS:continue
            row=node
            while row in parents:
                if row.get('resource-id','').endswith('/item_root'):break
                row=parents[row]
            if not row.get('resource-id','').endswith('/item_root'):
                # Current Android DocumentsUI exposes document selection on the
                # thumbnail at the left of the named row, not its Open action.
                row=parents.get(node,node)
            found[name]=row
        return xml,found
    for name in names:
        for attempt in range(3):
            xml,found=rows();assert name in found,name
            row=found[name]
            if row.get('selected')=='true' or any(n.get('checked')=='true' for n in row.iter()):break
            # Use the current title Y (list headers move when selection starts).
            x,y=position(xml,text=name,package=PICKERS)
            left=int(re.findall(r'\d+',row.get('bounds','[0,0][720,1280]'))[0])
            d.shell(f'input tap {left+48} {y}')
            def selected():
                _,current=rows();r=current.get(name)
                return r is not None and (r.get('selected')=='true' or any(n.get('checked')=='true' for n in r.iter()))
            try:d.wait(selected,'named document selected: '+name,timeout=8);break
            except AssertionError:
                if attempt==2:raise
    d.wait(lambda: position(d.ui(), text=f'{len(names)} selected', package=PICKERS), 'contagem exata de arquivos selecionados')


def active_wake_locks(power_dump):
    """Read only currently held locks, NOT Android's retained Wake Lock Log.
    A missing section is an error, never evidence that a lease was released.
    """
    match=re.search(r'(?m)^[ \t]*Wake Locks: size=(\d+)[ \t]*\r?$',power_dump)
    if not match:raise AssertionError('Active Wake Locks section missing from dumpsys power')
    if int(match.group(1))==0:return ''
    body=power_dump[match.end():].lstrip('\r\n')
    return re.split(r'\n[ \t]*\n',body,maxsplit=1)[0]


def completed_after_actual_sleep(log):
    """A fast model can finish AFTER screen-off but BEFORE the observer polls.
    Compare the system's actual Sleeping event with the native completion instead.
    """
    sleep=re.search(r'(?m)^(\d\d-\d\d \d\d:\d\d:\d\d\.\d+) .*PowerManagerService: Sleeping \(',log)
    done=re.search(r'(?m)^(\d\d-\d\d \d\d:\d\d:\d\d\.\d+) .*GGUF_NATIVE_COMPLETE',log)
    return bool(sleep and done and done.group(1)>sleep.group(1))
