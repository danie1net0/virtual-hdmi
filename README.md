<div align="center">

<sub><b>🇧🇷 Português</b> · <a href="README.en.md">🇺🇸 English</a></sub>

<img src="assets/readme-banner.svg" alt="Monitor virtual — um monitor HDMI virtual para máquinas sem monitor" width="100%">

<br>

<p>
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10 ou superior">
  <img src="https://img.shields.io/badge/GTK-4-4A86CF?style=for-the-badge&logo=gtk&logoColor=white" alt="GTK 4 e libadwaita">
  <img src="https://img.shields.io/badge/Linux-X11_·_Wayland-FCC624?style=for-the-badge&logo=linux&logoColor=black" alt="Linux, X11 e Wayland">
  <a href="https://gitlab.com/danie1net0/virtual-hdmi/-/pipelines"><img src="https://img.shields.io/gitlab/pipeline-status/danie1net0%2Fvirtual-hdmi?branch=master&style=for-the-badge&label=CI" alt="Estado do pipeline"></a>
  <a href="https://gitlab.com/danie1net0/virtual-hdmi/-/pipelines"><img src="https://img.shields.io/gitlab/pipeline-coverage/danie1net0%2Fvirtual-hdmi?branch=master&style=for-the-badge&label=cobertura" alt="Cobertura de testes medida no CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licença-MIT-F2C94C?style=for-the-badge" alt="Licença MIT"></a>
</p>

**Um EDID virtual no kernel e um app para trocar a resolução — sem nenhum monitor ligado.**<br>
<sub>Sem dependências além da biblioteca padrão do Python; o app usa GTK 4 e libadwaita.</sub>

<p>
  <a href="#-instalação-rápida"><b>Instalar</b></a> ·
  <a href="#-usar">Usar</a> ·
  <a href="#-edid">EDID</a> ·
  <a href="#-sessão-leve-sem-monitor">Sessão leve</a> ·
  <a href="#-ambientes-suportados">Ambientes</a> ·
  <a href="#-desenvolver">Desenvolver</a> ·
  <a href="#-verificar">Verificar</a>
</p>

<br>

<img src="assets/readme-preview.png" alt="Prévia da janela: estado da sessão e do EDID, lista de resoluções com 1920×1080 selecionada, chave Lembrar escolha e a seção de EDID com o botão Instalar" width="420">

</div>

<br>

## ✨ Destaques

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>🖥️ Tela sem tela</h3>
      Um EDID instalado no kernel faz a saída HDMI oferecer <b>3440×1440</b>, <b>3008×1260</b> e <b>2560×1080</b> sem monitor físico.
    </td>
    <td width="33%" valign="top">
      <h3>🔁 Troca na hora</h3>
      Escolha o modo na janela ou pelo terminal. Funciona em <b>GNOME, KDE, wlroots e X11</b>.
    </td>
    <td width="33%" valign="top">
      <h3>💾 Lembra a escolha</h3>
      A resolução volta sozinha a cada login, mesmo nos ambientes que não guardam a configuração.
    </td>
  </tr>
  <tr>
    <td width="33%" valign="top">
      <h3>🧮 EDID sob medida</h3>
      Gere um EDID novo com os relógios de pixel certos. O HDMI do <b>RK3566</b> recusa os que o PLL não gera exatamente.
    </td>
    <td width="33%" valign="top">
      <h3>🪶 Sessão leve</h3>
      Scripts para trocar o GNOME por <b>XFCE + LightDM</b> com login automático e manter a sessão ativa.
    </td>
    <td width="33%" valign="top">
      <h3>🧪 Confiável</h3>
      <b>100%</b> de cobertura de linhas e branches em Python e de linhas nos scripts shell.
    </td>
  </tr>
</table>

> [!NOTE]
> **Por que existe?** Máquinas sem monitor (um Orange Pi, um servidor, um notebook com a tampa fechada)
> costumam entregar à área de trabalho remota — Jump Desktop, VNC, RDP — uma tela pequena ou nenhuma.
> Com um EDID virtual, o sistema acredita que há um monitor ligado, com as resoluções que você definir.

## 🚀 Instalação rápida

Na pasta do projeto, **sem `sudo`**:

```sh
bash install.sh
```

O instalador confere o ambiente, copia o app para `~/.local/share/virtual-monitor`,
instala o ícone e cria o atalho **Monitor virtual** no menu. Só a instalação do EDID
(dentro do app) pede a senha de administrador.

### Requisitos

| | Requisito | Para quê |
|:-:| --- | --- |
| 🐧 | Linux com **GNOME, KDE, wlroots ou X11** | Trocar a resolução da sessão atual. |
| 🐍 | **Python 3.10+** | Executar o app e o gerador de EDID. |
| 🪟 | **GTK 4 e libadwaita** para Python | A janela e o backend do GNOME. |
| 🔐 | **`pkexec`** <sub>opcional</sub> | O botão que instala o EDID pede a senha por ele. |

No Debian, Ubuntu e Armbian:

```sh
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

As dependências ausentes são informadas antes da instalação.

### Opções do instalador

| Opção | Efeito |
| --- | --- |
| `--dev` | Cria links para esta pasta, para desenvolvimento. |
| `--dest-dir CAMINHO` | Instala em outra pasta de dados, sem atualizar caches nem o autostart. |
| `--skip-check` | Não confere as dependências do app. |
| `--uninstall` | Remove o app, o ícone, o atalho e o autostart da resolução. |
| `--help` | Exibe a ajuda. |

<details>
<summary><b>📁 Destino da instalação e migração</b></summary>

<br>

A instalação usa `$XDG_DATA_HOME` quando ele é um caminho absoluto, ou `~/.local/share`.

| Item | Caminho |
| --- | --- |
| App | `virtual-monitor/` |
| Atalho | `applications/virtual-monitor.desktop` |
| Ícone | `icons/hicolor/512x512/apps/virtual-monitor.png` |
| Resolução lembrada | `~/.config/virtual-monitor/mode.json` |
| Autostart da resolução | `~/.config/autostart/virtual-monitor-restore.desktop` |

Quem tinha a versão antiga, de nomes em português (`monitor-virtual`), é migrado na
instalação: a resolução salva é copiada, o autostart novo é criado e o app, o ícone
e o atalho antigos são removidos. O `--uninstall` mantém a resolução lembrada.

</details>

## 🖱️ Usar

Abra **Monitor virtual** no menu ou execute `python3 virtual-monitor.py`.

| Na janela | O que acontece |
| --- | --- |
| **Estado** | Mostra a sessão detectada, se o EDID virtual está ativo neste boot e a saída em uso. |
| **Resolução** | Toque em um modo para trocá-lo na hora; o atual vem marcado. |
| **Lembrar escolha** | Reaplica a resolução nos próximos logins. |
| **EDID** | Gera um EDID novo com os modos digitados e o instala, pedindo a senha. |

### No terminal

```sh
python3 virtual-monitor.py --list                  # sessão, conector e modos
python3 virtual-monitor.py --apply 2560x1080@59.98 # aplica e lembra no próximo login
python3 virtual-monitor.py --apply 1920x1080@60.00 --temp   # aplica sem lembrar
python3 virtual-monitor.py --restore               # reaplica o último modo lembrado
```

```text
session: X11 (xrandr)
connector: HDMI-1  (EDID at boot: HDMI-A-1)
 + 3440x1440@59.24  3440x1440  59.240 Hz
   2560x1080@59.98  2560x1080  59.980 Hz
*  1920x1080@60.00  1920x1080  60.000 Hz
```

`*` é o modo atual e `+` o preferido do EDID. O terminal usa o mesmo código da janela e
não abre GTK.

## 🔬 EDID

O EDID é o "cartão de visita" do monitor: a lista de resoluções que ele aceita. Instalado
no kernel (`drm.edid_firmware`), faz a saída HDMI-A-1 parecer um monitor real.

```sh
sudo bash scripts/install-edid.sh edid/ultrawide-rockchip.bin   # Orange Pi (RK3566)
sudo bash scripts/install-edid.sh                               # notebook Intel (edid/ultrawide.bin)
```

O script copia o EDID, inclui o arquivo na imagem de inicialização, confere se ele
entrou e só então ajusta os parâmetros do kernel — em `/boot/armbianEnv.txt` (Armbian)
ou no GRUB. Antes de mexer, guarda uma cópia `*.before-edid`; para desfazer, restaure-a e reinicie.

### Gerar um EDID novo

```sh
python3 -m virtual_monitor.edid saida.bin 3440x1440@312 2560x1080@216:60 --vic 16 --vic 4
```

Cada modo é `LARGURAxALTURA@RELÓGIO_MHZ[:HZ_ALVO]`; `--vic` acrescenta modos CEA padrão.
O relógio importa: o HDMI do Rockchip recusa com `NOCLOCK` todo modo cujo relógio o PLL
não gera exatamente.

Relógios (MHz) que o PLL do RK3566 gera exatamente: `312`, `297`, `241.5`, `216`, `200`,
`148.5` e `74.25`. O `edid/ultrawide-rockchip.bin` usa só esses.

<details>
<summary><b>📐 Como o gerador calcula os tempos</b></summary>

<br>

O gerador usa blanking reduzido, no estilo CVT. Para o relógio escolhido, ele define
`htotal` e `vtotal` de modo a chegar perto da taxa-alvo (60 Hz por padrão), sem criar
um blanking vertical enorme. O resultado é um EDID de 256 bytes: o bloco base, com os
três primeiros modos, e a extensão CTA-861, com os modos extras, os VICs e o bloco HDMI
(TMDS máximo de 340 MHz).

Modos fora dos limites do descritor (12 bits por medida, relógio de até 655,35 MHz),
nomes que não sejam ASCII e EDIDs que não cabem em 256 bytes são recusados com uma
mensagem clara.

</details>

## 🪶 Sessão leve sem monitor

Para uma máquina que só serve de servidor, o GNOME pesa. Dois scripts ajudam:

```sh
sudo bash scripts/install-xfce.sh [usuario]   # XFCE + LightDM com login automático
sudo bash scripts/install-session.sh          # mantém a sessão do login automático ativa
```

- `install-xfce.sh` instala XFCE, LightDM e o servidor X, configura o login automático
  e troca o gerenciador de login. O GNOME continua instalado; nada é reiniciado. Para
  voltar: `sudo systemctl enable gdm3.service && sudo reboot`.
- `install-session.sh` cria o serviço `keep-session`. Se o GDM abrir a tela de login por
  cima da sessão do login automático, ele devolve o seat à sessão do usuário — sem isso, a
  área de trabalho remota captura a tela de login. Log: `journalctl -u keep-session`.

## 🧭 Ambientes suportados

| Ambiente | Backend | Observação |
| --- | --- | --- |
| **GNOME** (Mutter) | DBus `org.gnome.Mutter.DisplayConfig` | O próprio GNOME guarda a escolha. |
| **KDE Plasma** | `kscreen-doctor` | Lembra pelo autostart do app. |
| **wlroots** (sway, labwc, Hyprland) | `wlr-randr` | Lembra pelo autostart do app. |
| **X11** (XFCE, MATE, i3) | `xrandr` | Lembra pelo autostart do app. |

O app escolhe o backend sozinho. Se a saída do EDID virtual estiver na linha de comando do
kernel, ele a usa; senão, usa a primeira saída conectada.

## 🛠️ Desenvolver

```sh
bash install.sh --dev   # instala links para este checkout
```

<details>
<summary><b>🗂️ Organização do código</b></summary>

<br>

| Caminho | Responsabilidade |
| --- | --- |
| [`virtual-monitor.py`](virtual-monitor.py) | Entrada: janela sem argumentos, terminal com opções. |
| [`virtual_monitor/edid.py`](virtual_monitor/edid.py) | Gerador de EDID: tempos, descritores, blocos e checksums. |
| [`virtual_monitor/displays.py`](virtual_monitor/displays.py) | Detecção do ambiente e backends Mutter, KScreen, wlr-randr e xrandr. |
| [`virtual_monitor/choice.py`](virtual_monitor/choice.py) | Resolução lembrada e autostart. |
| [`virtual_monitor/cli.py`](virtual_monitor/cli.py) · [`window.py`](virtual_monitor/window.py) | Modo terminal e janela GTK. |
| [`scripts/`](scripts/) | Scripts de sistema (root); todos aceitam `ROOT=` para testes. |
| [`edid/`](edid/) | EDIDs prontos para o Rockchip e para Intel. |
| [`install.sh`](install.sh) · [`data/`](data/) · [`assets/`](assets/) | Instalador, atalho e ícone. |
| [`tests/`](tests/) | Testes em Python e em shell, com o sistema simulado. |

</details>

Regras do projeto: só a biblioteca padrão (mais `gi` na janela), tudo em inglês e
scripts que rodam no bash 3.2 do macOS e no bash 5 do Linux — sem `sed -i`, `install -D`
nem arrays associativos.

## ✅ Verificar

```sh
bash tests/run.sh
```

| Comando | Verificação |
| --- | --- |
| `bash tests/run.sh` | Testes em Python (`unittest`) e em shell. |
| `bash tests/coverage.sh` | Cobertura: `coverage.py` com linhas e branches, e o xtrace para os scripts shell. |

Os testes de Python usam um GTK falso (`tests/fake_gi.py`), e os de shell trocam `apt`,
`systemctl`, `loginctl` e outros por stubs, gravando cada chamada. A cobertura exige
**100%**; a parte shell precisa de bash 4.1+ e de um usuário comum — no macOS, use o
container descrito no cabeçalho de [`tests/coverage.sh`](tests/coverage.sh).

O [CI do GitLab](.gitlab-ci.yml) roda os testes no Python 3.10 e no 3.13 e mede a cobertura
a cada push e merge request.

## 📄 Licença

Distribuído sob a [licença MIT](LICENSE). Use, modifique e redistribua à vontade.

O repositório principal fica no [GitLab](https://gitlab.com/danie1net0/virtual-hdmi);
o [GitHub](https://github.com/danie1net0/virtual-hdmi) é uma réplica automática.
Issues e merge requests são bem-vindos no GitLab.
