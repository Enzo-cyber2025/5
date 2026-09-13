"""Execute original JNI machine code with explicit external-call test doubles.

Unicorn executes both ISAs; this is a control-flow regression, NOT an inference
or Android-device test. No doubles or emulator are packaged into the APK.
"""
from io import BytesIO
import struct
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_X86, UC_ARCH_ARM64, UC_MODE_64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_RAX, UC_X86_REG_RDI, UC_X86_REG_RSI, UC_X86_REG_RDX, UC_X86_REG_RCX, UC_X86_REG_R8, UC_X86_REG_R9, UC_X86_REG_RSP
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5, UC_ARM64_REG_X6, UC_ARM64_REG_X7, UC_ARM64_REG_X8, UC_ARM64_REG_SP, UC_ARM64_REG_LR


def execute(data, budget=3, eos_at=0, fail_decode_at=0, cancel_at=0, invalid_handle=False):
    elf = ELFFile(BytesIO(data))
    arm = elf['e_machine'] == 'EM_AARCH64'
    cpu = Uc(UC_ARCH_ARM64 if arm else UC_ARCH_X86, UC_MODE_ARM if arm else UC_MODE_64)
    cpu.mem_map(0, 0x400000)
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD': cpu.mem_write(segment['p_vaddr'], segment.data())
    regs = ([UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
             UC_ARM64_REG_X4, UC_ARM64_REG_X5, UC_ARM64_REG_X6, UC_ARM64_REG_X7] if arm else
            [UC_X86_REG_RDI, UC_X86_REG_RSI, UC_X86_REG_RDX, UC_X86_REG_RCX, UC_X86_REG_R8, UC_X86_REG_R9])
    ret = UC_ARM64_REG_X0 if arm else UC_X86_REG_RAX
    env, table, engine, prompt, stop = 0x110000, 0x111000, 0x112000, 0x113000, 0x280000
    state = {'sampled': 0, 'tokens': 0, 'decodes': 0, 'done': None, 'done_calls': 0}
    def ptr(at, value): cpu.mem_write(at, struct.pack('<Q', value))
    def arg(i): return cpu.reg_read(regs[i])
    def result(v): cpu.reg_write(ret, v)
    def string(at):
        output = bytearray()
        while True:
            b = cpu.mem_read(at + len(output), 1)
            if b == b'\0': return output.decode()
            output.extend(b)
    hooks = {}
    def stub(name):
        address = 0x100000 + len(hooks) * 16
        hooks[address] = name
        cpu.mem_write(address, bytes.fromhex('c0035fd6') if arm else b'\xc3')
        return address
    symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
    for name, addr in symbols.items():
        if name.startswith('g_llama_'): ptr(addr, stub(name))
    dynsym = elf.get_section_by_name('.dynsym')
    for relocation in elf.get_section_by_name('.rela.plt').iter_relocations():
        ptr(relocation['r_offset'], stub(dynsym.get_symbol(relocation['r_info_sym']).name))
    for offset, name in {0x548: 'GetStringUTFChars', 0x550: 'ReleaseStringUTFChars',
                         0xf8: 'GetObjectClass', 0x108: 'GetMethodID', 0x538: 'NewStringUTF',
                         0x1e8: 'CallVoidMethod', 0xb8: 'DeleteLocalRef'}.items():
        ptr(table + offset, stub(name))
    ptr(env, table)
    ptr(engine + 8, 0x114000)
    ptr(engine + 16, 0x115000)
    cpu.mem_write(prompt, b'prompt\0')
    heap = [0x120000]
    def hook(uc, address, size, user):
        name = hooks.get(address)
        if name is None: return
        if name == 'GetStringUTFChars': result(prompt)
        elif name == 'GetObjectClass': result(1)
        elif name == 'GetMethodID':
            method = string(arg(2))
            assert method in ('onToken', 'onDone'), method
            result(1 if method == 'onToken' else 2)
        elif name == 'NewStringUTF': result(arg(1))
        elif name == 'CallVoidMethod':
            if arg(2) == 1:
                state['tokens'] += 1
                if cancel_at == state['tokens']: cpu.mem_write(engine + 32, struct.pack('<I', 1))
            else:
                assert arg(2) == 2
                state['done'] = arg(3) & 255
                state['done_calls'] += 1
        elif name in ('free', 'ReleaseStringUTFChars', 'DeleteLocalRef', 'g_llama_sampler_free', 'g_llama_sampler_chain_add'): pass
        elif name == 'strlen': result(len(string(arg(0))))
        elif name == 'malloc':
            result(heap[0]); heap[0] += 0x1000
        elif name == 'g_llama_tokenize': result(1)
        elif name in ('g_llama_sampler_chain_default_params', 'g_llama_vocab_bos'): result(0)
        elif name in ('g_llama_sampler_chain_init', 'g_llama_sampler_init_greedy'): result(0x116000)
        elif name == 'g_llama_batch_get_one':
            output = cpu.reg_read(UC_ARM64_REG_X8) if arm else arg(0)
            cpu.mem_write(output, struct.pack('<I', 1) + bytes(52))
            result(output)
        elif name == 'g_llama_decode':
            state['decodes'] += 1
            result(1 if fail_decode_at == state['decodes'] else 0)
        elif name == 'g_llama_sampler_sample':
            state['sampled'] += 1
            result(42)
        elif name == 'g_llama_token_is_eog': result(int(eos_at == state['sampled']))
        elif name == 'g_llama_token_to_piece':
            cpu.mem_write(arg(2), b'x\0'); result(1)
        else: raise AssertionError('Unexpected external call: ' + name)
    cpu.hook_add(UC_HOOK_CODE, hook)
    args = [env, 0, 0 if invalid_handle else engine, prompt, budget & 0xffffffff, 0]
    for reg, val in zip(regs, args): cpu.reg_write(reg, val)
    if arm:
        cpu.reg_write(UC_ARM64_REG_X6, 0)
        cpu.reg_write(UC_ARM64_REG_X7, 1)
        cpu.reg_write(UC_ARM64_REG_SP, 0x300000)
        cpu.reg_write(UC_ARM64_REG_LR, stop)
    else:
        sp = 0x300008
        cpu.reg_write(UC_X86_REG_RSP, sp)
        ptr(sp, stop); ptr(sp + 8, 0); ptr(sp + 16, 1)
    entry = symbols['Java_com_ggufchat_app_Native_generate']
    cpu.emu_start(entry, stop, count=1000000)
    from unicorn.arm64_const import UC_ARM64_REG_PC
    from unicorn.x86_const import UC_X86_REG_RIP
    assert cpu.reg_read(UC_ARM64_REG_PC if arm else UC_X86_REG_RIP) == stop, 'Native function did not return'
    state['result'] = cpu.reg_read(ret) & 255
    return state
