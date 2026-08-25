#!/usr/bin/env python3
# =============================================================================
# mkisouefi.py — monta um ISO UEFI-bootável (El Torito EFI) a partir do kernel
# com EFI stub + initramfs embutido. Usa pycdlib.
# =============================================================================
import sys, os, pycdlib

def main():
    bzimage = sys.argv[1]
    outiso  = sys.argv[2]
    efiimg  = sys.argv[3] if len(sys.argv) > 3 else "efi.img"
    if not os.path.exists(bzimage):
        print("ERRO: kernel não encontrado:", bzimage); sys.exit(1)
    if not os.path.exists(efiimg):
        print("ERRO: imagem FAT não encontrada:", efiimg); sys.exit(1)

    iso = pycdlib.PyCdlib()
    iso.new(vol_ident="NOVALINUX", joliet=3, rock_ridge="1.09")

    # cria diretório /BOOT (ISO9660 exige maiúsculas); Joliet/RR preservam "boot"
    iso.add_directory("/BOOT", rr_name="boot", joliet_path="/boot")

    # 1) adiciona a imagem FAT como arquivo no ISO (caminho ISO: /BOOT/EFI.IMG)
    # NOTA: manter o file object aberto até iso.write (pycdlib lê durante o write)
    fp = open(efiimg, "rb")
    iso.add_fp(fp, os.path.getsize(efiimg), "/BOOT/EFI.IMG", rr_name="efi.img", joliet_path="/boot/efi.img")

    # 2) registra a imagem como boot El Torito EFI (referencia o arquivo já no ISO)
    iso.add_eltorito(bootfile_path="/BOOT/EFI.IMG",
                     boot_load_size=os.path.getsize(efiimg) // 512,
                     platform_id=0xef,      # UEFI
                     efi=True,
                     media_name="noemul",
                     bootable=True)

    # 3) kernel no ISO (acessível ao usuário)
    kfp = open(bzimage, "rb")
    iso.add_fp(kfp, os.path.getsize(bzimage), "/BOOT/VMLINUZ", rr_name="vmlinuz", joliet_path="/boot/vmlinuz")

    iso.write(outiso)
    iso.close()
    print("ISO UEFI escrito:", outiso, os.path.getsize(outiso), "bytes")
    print("COMPLETO=1")

if __name__ == "__main__":
    main()
