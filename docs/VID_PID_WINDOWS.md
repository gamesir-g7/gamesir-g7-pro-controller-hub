# Descobrir VID/PID no Windows

Conecte o controle no modo que deseja testar.

PowerShell:

```powershell
Get-PnpDevice -PresentOnly |
Where-Object {$_.InstanceId -match 'VID_.*PID_'} |
Where-Object {$_.FriendlyName -match 'Controller|Gamepad|HID|Xbox|GameSir'} |
Format-List FriendlyName,InstanceId
```

Procure:

```text
VID_XXXX&PID_YYYY
```

## Exemplo real — GameSir T4 Nova Lite

Modo verde:

```text
USB\VID_3537&PID_1040&MI_00
Xbox 360 Controller for Windows
```

Modo amarelo:

```text
HID\VID_3537&PID_1041...
```

## Testar botões DInput

Execute:

```text
joy.cpl
```

Abra Propriedades do controle e pressione cada botão.

Lembre-se: a numeração mostrada pelo `joy.cpl` descreve o relatório do Windows e não necessariamente o mapeamento interno do PS3.
