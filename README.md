# Stereo Alerta IA — SM-A556E

Aplicativo Android experimental de distância métrica com duas câmeras traseiras físicas, IA neural estéreo e alerta sonoro.

## Download direto

[**⬇️ Baixar Stereo-Alerta-IA-SM-A556E-v1.0.0.apk**](https://github.com/Enzo-cyber2025/5/raw/refs/heads/arena/01a034a7-5/Stereo-Alerta-IA-SM-A556E-v1.0.0.apk)

- Versão: `1.0.0`
- Android mínimo: Android 9 / API 28
- Arquitetura de execução: `ARM64-v8a`
- SHA-256 do APK: `12e08fd3d08d734b3b83a8ac08680bafdfb78865ec49691b1be6c7b961c632c0`
- Assinatura: APK Signature Scheme v3, RSA 4096 bits

## Instalação e primeiro uso

1. Baixe e instale o APK.
2. Abra **Stereo Alerta IA** e conceda a permissão de câmera.
3. Mantenha conexão com a internet no primeiro uso.
4. Toque em **INICIAR**. O aplicativo baixa o LiteRT 2.2.0 e o modelo neural estéreo HITNet.
5. Aguarde a instalação e compilação do modelo na GPU.

Os arquivos são instalados no armazenamento privado do aplicativo. Depois que a preparação termina com sucesso, o runtime e o modelo permanecem no aparelho e o aplicativo funciona **offline**. Se o aplicativo for desinstalado ou seus dados forem apagados, o download será necessário novamente.

## Implementação

- Camera2 API com dois streams físicos traseiros `YUV_420_888` simultâneos.
- Exige câmera lógica `LOGICAL_MULTI_CAMERA`, sincronização calibrada, pose, translação e intrínsecos dos sensores.
- Modelo neural estéreo HITNet com duas imagens como entrada.
- LiteRT `CompiledModel` 2.2.0 solicitado somente com `Accelerator.GPU`.
- Sem fallback para CPU, câmera única ou SGBM.
- Distância em metros calculada por `focal × baseline / disparidade neural`.
- Região central com decisão por maioria dos pixels válidos.
- Zona de perigo ajustável entre `0,5 m` e `5,0 m`.
- Alarme agudo e intermitente usando `SoundPool` e `AudioAttributes.USAGE_ALARM`.
- Pré-visualização, distância, botão iniciar/parar e indicação visual de perigo.

## Incompatibilidade

Se o firmware do SM-A556E não expuser o par físico e os metadados obrigatórios, recusar a sessão simultânea ou a GPU não conseguir compilar o modelo, o aplicativo mostrará **Execução recusada**. Isso é intencional e não ativa nenhuma implementação simplificada.

> Aplicativo experimental, não certificado como equipamento de segurança. A precisão depende da calibração fornecida pelo firmware e do alinhamento das câmeras.
