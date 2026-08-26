# Xclipse64

Launcher Android para executar ambientes Windows ARM64 com **Box64 / Box86**, **DXVK / VKD3D-Proton** e uma camada Vulkan opcional para GPUs **Samsung Xclipse**.

## APK

O APK completo está no GitHub como [`Xclipse64-v0.2.0-full.apk`](https://github.com/Enzo-cyber2025/5/raw/2ff4f27d0af8a2a60b70f1d5bb7ae92c4790f1f1/Xclipse64-v0.2.0-full.apk) e também é referenciado pelo release [v0.2.0](https://github.com/Enzo-cyber2025/5/releases/tag/v0.2.0). O checksum está em `SHA256SUMS-full.txt`. O release inclui o núcleo Box64 Bionic, DXVK, VKD3D, D8VK e uma camada BCn; Wine/Proton e jogos continuam sendo adicionados pelo usuário.

## O que o aplicativo faz

- Seleciona perfil Windows **x64 (Box64)** ou **x86-32 (Box32/WOWBox64 e Box86 quando fornecido pelo runtime)**.
- Permite escolher um `.exe` pelo Storage Access Framework do Android.
- Já instala do APK o núcleo Box64 Bionic, WOWBox64, DXVK, VKD3D, D8VK e a camada BCn.
- Permite importar um pacote `.zip` de Wine/Proton ou componentes adicionais para o armazenamento privado.
- Procura `box64` / `box86` e `wine64` / `wine` no runtime importado, executando o processo com variáveis de ambiente isoladas.
- Seleciona DXVK para DirectX 9/10/11, VKD3D-Proton para DirectX 12 ou WineD3D para compatibilidade.
- Detecta a presença do Vulkan do sistema e identifica sinais de hardware Xclipse/Exynos.
- Expõe a camada BCn embutida e camadas Vulkan/Xclipse adicionais pelo `VK_LAYER_PATH`.
- Evita permissões amplas de armazenamento e bloqueia path traversal e ZIPs acima do limite durante a importação.

## Importante sobre Xclipse e os runtimes

O driver Vulkan principal do Android é um componente do fabricante e não pode ser substituído com segurança por um APK comum. Por isso, o Xclipse64 usa o driver Samsung do sistema como backend; a camada opcional importada é apenas uma camada de compatibilidade Vulkan. Ela deve ser compatível com o aparelho e ter uma licença que permita seu uso.

Box64 traduz binários Linux **x86_64** para ARM64. O APK completo já traz o tradutor Bionic; para binários x86 de 32 bits, ele traz WOWBox64 e aceita Box86/Box32 adicional no runtime. Wine/Proton, jogos e uma distribuição Windows continuam não sendo componentes de um driver e devem ser fornecidos separadamente.

## Conteúdo do APK completo

O APK `v0.2.0` copia para o armazenamento privado no primeiro início um Box64 Bionic ARM64, WOWBox64, DXVK 2.3.1, VKD3D 2.14.1, D8VK 1.0 e a camada BCn Vulkan. Os DLLs são configurados automaticamente no `WINEDLLPATH` conforme o tradutor selecionado.

Wine/Proton não é um driver gráfico e não é um substituto de Box64; é um runtime independente. Ele precisa ser importado em ZIP pelo botão **Instalar runtime**. O driver Samsung do Exynos 1480/Xclipse 530 permanece sendo o backend do Android, como exigido pelo modelo de segurança do sistema. O APK é assinado com uma chave debug para permitir instalação imediata; uma distribuição final deve trocar a configuração de assinatura por uma chave de produção.
