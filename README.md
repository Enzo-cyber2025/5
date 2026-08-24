# Stereo Alerta IA — SM-A556E

Aplicativo Android experimental para estimativa de distância com duas câmeras traseiras físicas e alerta sonoro de proximidade.

## Download

[**Baixar Stereo-Alerta-IA-SM-A556E-v1.0.0.apk**](./Stereo-Alerta-IA-SM-A556E-v1.0.0.apk)

- Versão: `1.0.0`
- Arquitetura: `ARM64-v8a`
- Android mínimo: Android 9 / API 28
- SHA-256: `12e08fd3d08d734b3b83a8ac08680bafdfb78865ec49691b1be6c7b961c632c0`
- Assinatura: APK Signature Scheme v3, RSA 4096 bits

## Instalação

1. Baixe o APK pelo link acima.
2. No SM-A556E, permita a instalação de aplicativos desconhecidos para o navegador ou gerenciador de arquivos utilizado.
3. Abra o APK e toque em **Instalar**.
4. Inicie **Stereo Alerta IA** e conceda a permissão de câmera.
5. Mantenha conexão com a internet na primeira inicialização. O aplicativo instala, em armazenamento privado, o runtime oficial LiteRT 2.2.0 e o modelo neural estéreo HITNet.
6. Toque em **Iniciar** e ajuste a zona de perigo entre `0,5 m` e `5,0 m`.

## Funcionamento

- Camera2 com dois streams físicos traseiros `YUV_420_888` de mesmo tamanho.
- Exige `LOGICAL_MULTI_CAMERA` com sincronização calibrada.
- Exige pose, translação e calibração intrínseca dos dois sensores.
- HITNet processa os dois quadros no LiteRT `CompiledModel` usando exclusivamente `Accelerator.GPU`.
- A distância usa a disparidade neural, distância física entre câmeras e distância focal fornecidas pela Camera2.
- O alerta agudo e intermitente é reproduzido com `SoundPool`.
- Não existe fallback para CPU, câmera única ou algoritmo clássico de disparidade.

## Política de incompatibilidade

Se o firmware do SM-A556E não expuser qualquer requisito obrigatório, se recusar a sessão simultânea ou se a GPU não compilar integralmente o modelo, o aplicativo exibirá **Execução recusada** e informará o motivo. Isso é intencional.

> Não é um dispositivo de segurança certificado. A precisão depende da calibração publicada pelo firmware, do alinhamento óptico, da iluminação e da compatibilidade do par de câmeras.
