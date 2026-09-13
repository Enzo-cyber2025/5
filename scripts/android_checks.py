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


def gpu_offloaded(log):
    # Merely loading libggml-vulkan.so/SwiftShader is NOT proof of GPU inference.
    return bool(re.search(r"offloaded\s+[1-9]\d*(?:/\d+)?\s+layers?\s+to\s+GPU", log, re.I))


def basic_response_quality(greeting, arithmetic):
    """Conservative sanity check for the suite's two fixed prompts, not a benchmark."""
    if not re.search(r'\b(hello|hi|hey|greetings|good morning|good afternoon|good evening)\b', greeting, re.I):
        raise AssertionError('Resposta não contém uma saudação pertinente ao primeiro pedido')
    answer = arithmetic.casefold().replace('*', '').replace('`', '').strip(' \n.!')
    accepted = {'4', 'four', '2+2=4', '2 + 2 = 4', 'two plus two is four',
                'two plus two equals four', 'two plus two is 4', 'two plus two equals 4',
                'the answer is 4', 'the answer is four'}
    if answer not in accepted:
        raise AssertionError('Resposta à pergunta 2 + 2 não corresponde à resposta simples esperada: 4')
    return True


def vulkan_offloaded(log):
    """Require initialized Vulkan plus actual positive layer offload, not availability."""
    initialized = re.search(r'registered backend Vulkan|ggml_vulkan: Found [1-9]', log, re.I)
    return bool(initialized) and gpu_offloaded(log)
