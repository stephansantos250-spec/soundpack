# soundpack — ATS&ETS2

Gerenciador de sons com temas **Claro e Escuro**, acompanhado do novo **plugin_files.zip** fornecido pelo usuário.

## Download atualizado — pacote 2.1.1

Baixe **soundpack-completo-v2.1.1.zip** em [Releases](https://github.com/stephansantos250-spec/soundpack/releases/latest).

A pasta de roncos do pacote anterior foi retirada. Esta versão inclui apenas o app e o novo plugin enviado, sem os 97 bancos de som anteriores. A versão do pacote não indica uma nova versão da DLL: nenhum número de versão do plugin foi inferido.

```text
soundpack/
├── aplicativo/           # App, scripts, logo e ícone
├── plugin_files.zip      # Novo arquivo, preservado sem alteração
├── CONTEUDO_PLUGIN.csv   # Arquivos internos do plugin e SHA-256
├── docs/tema-escuro.png
└── README.md
```

## Instalação pelo aplicativo

1. **Feche o jogo e faça backup** da pasta `bin\win_x64\plugins` e de `%APPDATA%\ATS_Pack_Manager`.
2. Extraia o pacote completo em uma pasta nova. Abra `aplicativo\1_EXECUTAR.bat` com Python 64 bits e Tkinter instalados.
3. Escolha **ATS** ou **ETS2** no topo da janela. Em **Instalação**, selecione a pasta principal desse jogo.
4. Clique em **Importar ZIP offline** e selecione o novo `plugin_files.zip` que acompanha este pacote. O app instala a DLL e escolhe o `master.bank` da pasta ATS ou ETS2 conforme o jogo selecionado.
5. O novo arquivo **não contém roncos adicionais**. Para usar sons personalizados, importe bancos compatíveis pela Biblioteca.

O instalador do app preserva os arquivos locais `selected.bank.txt` e `sound_levels.txt` se já existirem. Ele também **não apaga os bancos antigos da pasta do seu computador**. Para uma instalação limpa, faça backup e mova a pasta antiga `ts-fmod-plugin` para fora de `plugins`, antes de importar o novo ZIP. Não apague seus únicos exemplares dos roncos.

Se não há bancos de som importados, deixe a seleção vazia. O `selected.bank.txt` do ZIP original pode citar bancos de exemplo que não estão incluídos.

## Instalação manual (opcional)

Extraia `plugin_files.zip` em uma pasta temporária. Copie `ts-fmod-plugin.dll` e a pasta `ts-fmod-plugin` para `bin\win_x64\plugins` do jogo. Depois copie **somente** o `master.bank` da pasta **ATS** ou **ETS2**, conforme o jogo, para dentro de `bin\win_x64\plugins\ts-fmod-plugin`. As pastas ATS e ETS2 do ZIP são alternativas de instalação, não pacotes de roncos.

## Aparência e executável

No menu lateral, em **Aparência**, escolha **Claro** ou **Escuro**. A preferência é salva. Para gerar um executável no Windows, use `aplicativo\2_CRIAR_EXE.bat`. **Não há EXE compilado no download.**

![Tema escuro](docs/tema-escuro.png)

## Conteúdo e limites

O novo ZIP contém:
- `ts-fmod-plugin.dll`;
- `ATS/master.bank` e `ETS2/master.bank`;
- `ts-fmod-plugin/selected.bank.txt` e `ts-fmod-plugin/sound_levels.txt`.

Nenhum banco de ronco anterior nem som sintetizado foi incluído. A aba Caminhonetes organiza gravações WAV para preparação, sem compilá-las em .bank. A seleção do plugin é global, não automática por veículo.

Projeto do plugin: https://github.com/dariowouters/ts-fmod-plugin

Os materiais de terceiros mantêm os direitos dos respectivos autores; este repositório não lhes atribui uma licença nova. O novo `plugin_files.zip` foi enviado pelo usuário; sua procedência e versão não foram verificadas de forma independente.

## Verificação

ZIPs conferidos por CRC e arquivo do plugin preservado byte a byte. `CONTEUDO_PLUGIN.csv` lista os hashes dos arquivos internos. A interface do app e os fluxos locais já foram testados no Linux. **A nova DLL, reprodução e integração com ATS/ETS2 não foram testadas no Windows.**
