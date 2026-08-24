# Stereo Alerta IA — SM-A556E

Aplicativo Android experimental de distância métrica com duas câmeras traseiras físicas, IA neural estéreo, alerta sonoro e execução sobre outros aplicativos.

## Download direto

[**⬇️ Baixar Stereo-Alerta-IA-SM-A556E-v1.1.0.apk**](https://github.com/Enzo-cyber2025/5/raw/refs/heads/arena/01a034a7-5/Stereo-Alerta-IA-SM-A556E-v1.1.0.apk)

- Versão: `1.1.0`
- Android mínimo: Android 9 / API 28
- Arquitetura de execução: `ARM64-v8a`
- SHA-256: `2d1257e7a6e1d0680f15a02e37ab46d881af3e60858a90fabaf29b707941d5fd`
- Assinatura: APK Signature Scheme v3, RSA 4096 bits

## Instalação e primeiro uso

1. Baixe e instale o APK.
2. Conceda as permissões de câmera e notificações.
3. Quando solicitado, habilite **Permitir exibição sobre outros apps**.
4. Mantenha internet disponível no primeiro uso.
5. Toque em **INICIAR** e aguarde o download e a compilação do LiteRT 2.2.0 e do HITNet.

Os componentes são instalados no armazenamento privado do aplicativo. Após a preparação bem-sucedida, o aplicativo funciona offline. Desinstalar o aplicativo ou apagar seus dados exige novo download.

## Uso sobre YouTube e outros aplicativos

Depois de tocar em **INICIAR**, o processamento é transferido para um `ForegroundService` do tipo `camera`:

- a análise continua quando o aplicativo sai da tela;
- um painel flutuante mostra distância e estado de perigo sobre outros apps;
- o alarme continua sendo reproduzido;
- uma notificação permanente indica que câmera e IA estão ativas;
- use **PARAR** no painel, na notificação ou no aplicativo para encerrar completamente.

O serviço deve ser iniciado enquanto o aplicativo está visível. Outro aplicativo que tentar usar a câmera simultaneamente poderá causar indisponibilidade da câmera.

## Implementação

- Camera2 API com dois streams físicos traseiros `YUV_420_888` simultâneos.
- Exige `LOGICAL_MULTI_CAMERA`, sincronização calibrada, pose, translação e intrínsecos.
- HITNet com duas imagens como entrada e profundidade métrica por `focal × baseline / disparidade neural`.
- LiteRT 2.2.0 `CompiledModel`, solicitado exclusivamente com `Accelerator.GPU`.
- Sem fallback para CPU, câmera única ou SGBM.
- Região central com decisão por maioria dos pixels válidos.
- Zona de perigo ajustável entre `0,5 m` e `5,0 m`.
- Alarme intermitente com `SoundPool` e `AudioAttributes.USAGE_ALARM`.
- `FOREGROUND_SERVICE_CAMERA`, notificação persistente e overlay `TYPE_APPLICATION_OVERLAY`.

## Incompatibilidade

Se o firmware não expuser o par físico ou metadados obrigatórios, recusar a sessão simultânea, ou a GPU não compilar o modelo, o aplicativo mostrará **Execução recusada** sem ativar implementação simplificada.

> Aplicativo experimental, não certificado como equipamento de segurança.
