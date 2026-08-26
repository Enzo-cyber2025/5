# Xclipse64

Launcher Android para executar ambientes Windows ARM64 com **Box64 / Box86**, **DXVK / VKD3D-Proton** e uma camada Vulkan opcional para GPUs **Samsung Xclipse**.

## APK

O APK instalável está no GitHub como [`Xclipse64-v0.1.0.apk`](https://github.com/Enzo-cyber2025/5/raw/349a7c07f9fc25413d8b4a89500342d33302d67f/Xclipse64-v0.1.0.apk) e também é referenciado pelo release [v0.1.0](https://github.com/Enzo-cyber2025/5/releases/tag/v0.1.0). O checksum está em `SHA256SUMS.txt`. O release não inclui runtimes, jogos, Wine, tradutores gráficos ou drivers proprietários.

## O que o aplicativo faz

- Seleciona perfil Windows **x64 (Box64)** ou **x86-32 (Box86, com Box64 quando disponível)**.
- Permite escolher um `.exe` pelo Storage Access Framework do Android.
- Importa um pacote `.zip` de runtime e extrai-o para o armazenamento privado do aplicativo.
- Procura `box64` / `box86` e `wine64` / `wine` no runtime importado, executando o processo com variáveis de ambiente isoladas.
- Seleciona DXVK para DirectX 9/10/11, VKD3D-Proton para DirectX 12 ou WineD3D para compatibilidade.
- Detecta a presença do Vulkan do sistema e identifica sinais de hardware Xclipse/Exynos.
- Importa uma camada Vulkan/Xclipse fornecida pelo usuário e expõe `VK_LAYER_PATH` ao runtime.
- Evita permissões amplas de armazenamento e bloqueia path traversal e ZIPs acima do limite durante a importação.

## Importante sobre Xclipse e os runtimes

O driver Vulkan principal do Android é um componente do fabricante e não pode ser substituído com segurança por um APK comum. Por isso, o Xclipse64 usa o driver Samsung do sistema como backend; a camada opcional importada é apenas uma camada de compatibilidade Vulkan. Ela deve ser compatível com o aparelho e ter uma licença que permita seu uso.

Box64 traduz binários Linux **x86_64** para ARM64. Para binários x86 de 32 bits, o runtime precisa fornecer Box86 ou uma build do Box64 com integração Box32. Um APK sozinho não contém Wine, Box64, DXVK, VKD3D-Proton, jogos nem uma distribuição Windows.

## Build reproduzível

A Action em `.github/workflows/build-apk.yml` compila `app-release.apk` com Java 17, Android API 35 e Gradle 8.10.2. O release é assinado com a chave debug para permitir instalação imediata; uma distribuição final deve trocar a configuração de assinatura por uma chave de produção.
