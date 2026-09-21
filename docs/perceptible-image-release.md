# Entrega condicionada a ganho perceptível: imagens retidas

Não entregar candidato sem ganho. O critério desta rodada é **ao menos 2× de
redução da espera e 10 segundos poupados em cada um de dois pares**, no emulador,
com mesmo modelo, pixels, parâmetros e conteúdo. A métrica é Enviar → primeiro
texto visível. Isso se refere à reativação de imagens já processadas; não é uma
promessa para a primeira imagem, hardware físico ou tokens/s de texto.

Candidato: payload compilado e funcionalmente testado no run 35252559185,
fonte 81bc70c, APK SHA-256 2b444a73090dff9bd6d4ce6d199349cafd5e9ae73b83cc34e05101e7f77727cc.
Controle: APK entregue 323fd5a33667c6cab278699e97c89fe253e1bb7acead45b869729bf022eb9f5c.
Sem recompilar o modelo ou ativar QKV/batch/RGB-packing experimental. O modelo e
o projetor continuam com cálculo tensorial Vulkan estrito. Decode/normalização/
layout de entrada não foram todos migrados para GPU nesse payload.

Cada observação parte de Engine novo, carrega A+B e gera; exclui A e gera; reativa
A e mede. A sequência inteira é executada nos dois APKs. Os pares seguem AB/BA,
no mesmo runner. Não há cache desligado, hashes/readback diagnósticos, corte de
imagem/texto ou demora artificial. Ações de exclusão são replay explícito da
opção de anexos e são iguais nas duas versões. Históricos brutos, tokens,
dimensões preparadas e registros de avaliação das imagens devem coincidir.

O candidato deve mostrar zero recodificações do projetor na etapa medida,
enquanto o controle deve realmente recodificar as mesmas imagens. A passagem
não se baseia apenas em contadores: exige a redução de latência nos dois pares,
mais testes de renderer/Copy, decoder Android e conclusão com tela apagada.

O teste utiliza assinatura descartável igual nas duas cópias para preservar
modelos/chats entre trocas no emulador. Essa assinatura não é uma chave de entrega.
Somente após PASS o CI disponibiliza o payload aprovado para assinatura local
persistente e conferência de igualdade de todos os dados não relacionados à
assinatura. Não substituir o APK entregue nem orientar desinstalação silenciosa.
Uma nova assinatura pode impedir atualização sobre a instalação antiga; os dados
devem ser preservados antes de qualquer remoção. Não há garantia de GPU física.
