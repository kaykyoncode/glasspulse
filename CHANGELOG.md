# Changelog

Mudanças importantes do CorePulse. O projeto não tem número de versão: cada entrada
corresponde a um commit no `main`, com a data em que entrou.

## 2026-11-13 — CorePulse

- Nome CorePulse na interface, bandeja, atalhos, documentação e repositório.
- Entrada `corepulse.pyw`, pacote `src/corepulse/` e configurações em `%APPDATA%\CorePulse`.
- Migração das preferências e do estado do Modo Jogo das instalações anteriores, sem sobrescrever
  uma configuração CorePulse existente.
- Tarefa elevada do Modo Jogo em `\CorePulse\Modo Jogo`; ao registrá-la, a tarefa anterior é removida.

## 2026-11-07 — Não cobre mais os seus apps

- **Alfinete desligado por padrão.** O widget fica atrás de todos os apps, logo acima da área de
  trabalho, e não passa mais para a frente quando é clicado, ativado ou arrastado.
- `HWND_BOTTOM` ao abrir, ao ser ativado, no fim do arraste, depois de um menu e ao soltar o alfinete;
  qualquer outra mudança de Z-order continua sendo trocada por "para o fundo".
- Alfinete ligado: `HWND_TOPMOST`. Ao soltar: `HWND_NOTOPMOST` e depois `HWND_BOTTOM`, com o aviso
  "Atrás dos seus apps de novo."
- Aberto de propósito (ícone da bandeja ou o atalho aberto de novo), aparece na frente dos apps e volta
  para trás quando o foco vai para outra janela. Com o widget visível atrás dos apps, o 1º clique no
  ícone da bandeja traz para a frente e o seguinte oculta.
- Migração: as configurações ganharam o campo `"versao"`. Quem já tinha configurações salvas estava com
  o alfinete ligado só porque era o padrão antigo; ele é desligado uma única vez.
- Correção: depois de uma ativação, o `HWND_TOPMOST` às vezes não pegava. As chamadas de Z-order usam
  `SWP_NOOWNERZORDER` e o topo é conferido.

## 2026-11-07 — Visual novo

- Cards pretos em formato de pasta com "•••" (menu), números em Barlow Semi Condensed Light, rótulos
  em caixa alta, ícones em traço e um único painel neon amarelo (`#ffe83a`) na memória.
- Sem acrílico nem cantos, borda ou sombra do DWM; a parte transparente da janela não pega clique.
- Arraste segurando em qualquer parte do card, sempre inteiro dentro do monitor; volta para a tela
  quando um monitor desliga ou muda de resolução/escala; troca coluna/painel se o layout não couber.
- Alfinete no cabeçalho para fixar por cima das janelas (nesta versão vinha ligado por padrão).
- Saem os menus Tema e Vidro; o tema só escolhe o ícone da bandeja.

## 2026-11-02 — Modo Jogo

- Um clique fecha o que está aberto, pausa serviços em segundo plano e deixa o PC só para o jogo;
  outro clique devolve tudo como estava.

## 2026-10-28 — Temas e ícones

- Temas Noite, Sukuna e Gojo (JSON em `temas/`) e ícones novos.

## 2026-10-28 — Primeira versão

- Widget de área de trabalho com CPU, memória, GPU NVIDIA, rede, discos e maiores usos de RAM, em vidro
  acrílico do Windows 11.
