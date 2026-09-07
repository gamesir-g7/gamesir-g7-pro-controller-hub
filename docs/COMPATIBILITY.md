# Compatibilidade de controles

PS3xPAD trabalha melhor quando o protocolo do controle corresponde a um tipo que o plugin entende.

## Tipos úteis

| XTYPE/PTYPE | Uso típico |
|---|---|
| `XTYPE_XBOX360` | Controle XInput/Xbox 360 com fio ou dongle que se apresenta como controle 360 cabeado |
| `XTYPE_XBOX360W` | Receptor wireless Xbox 360 |
| `XTYPE_XBOXONE` | Controle/protocolo Xbox One |
| `XTYPE_XBOX` | Xbox original |
| `PTYPE_PS3` | Dispositivo compatível com pad PS3 |
| `PTYPE_PS4` | DualShock 4 |
| `PTYPE_BT` | Adaptador Bluetooth suportado |

## Suporte padrão documentado pelo PS3xPAD v0.8

- Xbox 360 com fio
- Xbox One com fio
- Xbox 360 wireless com receptor USB
- DualShock 4 com fio
- DualShock 4 wireless com adaptador USB

## Dispositivos personalizados

Formato:

```text
VID, PID, NAME, XTYPE
```

Exemplo:

```text
0x3537, 0x1040, GameSir T4 Nova Lite, XTYPE_XBOX360
```

## GameSir T4 Nova Lite

| Modo | VID:PID | Resultado |
|---|---|---|
| Verde / XInput | `3537:1040` | Alvo correto para PS3xPAD |
| Amarelo / HID-DInput | `3537:1041` | PS3 recebe entrada nativamente, mas mapeamento fica incorreto; não basta assumir XInput |

## Outros controles podem funcionar?

### Boa chance

Se o Windows mostrar algo equivalente a:

```text
Xbox 360 Controller for Windows
```

o primeiro teste recomendado é:

```text
0xVID, 0xPID, Nome do controle, XTYPE_XBOX360
```

### Não garantido

Controles que aparecem apenas como:

```text
HID-compliant game controller
```

ou DInput genérico podem usar relatórios HID próprios. Nesses casos, adicionar apenas VID/PID pode não ser suficiente.

### Limitações

- Compatibilidade varia por firmware, exploit, jogo e revisão do controle.
- PS2/PSP emulados não são suportados pelo PS3xPAD segundo a documentação comunitária.
- Recursos como rumble, Sixaxis, botão PS e remapeamento podem exigir configuração adicional.
