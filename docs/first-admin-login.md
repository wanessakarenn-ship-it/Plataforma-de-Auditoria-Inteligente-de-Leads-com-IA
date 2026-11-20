# Primeiro login administrativo local

Este procedimento descreve a configuração local do Firebase Authentication para o projeto `prime-amulet-439718-e3`. Na homologação da Sprint 02, a configuração Web foi verificada, o primeiro administrador foi provisionado pelo bootstrap aprovado e as claims da conta foram confirmadas por consulta de leitura. A sessão autenticada local carregou os endpoints administrativos sem exibir ou registrar o ID token. Não coloque tokens, chaves de conta de serviço ou arquivos ADC no repositório, no frontend ou em `.env`.

## 1. Configurar Firebase Authentication no Console

1. Abra o Firebase Console e selecione o projeto `prime-amulet-439718-e3`.
2. Em **Authentication → Get started → Sign-in method**, habilite o provedor escolhido:
   - **Email/Password** para criar uma conta de teste controlada; ou
   - **Google**, configurando o e-mail de suporte exigido pelo Console.
3. Em **Authentication → Settings → Authorized domains**, confirme que `localhost` está autorizado para desenvolvimento local. A consulta de leitura desta etapa confirmou que está autorizado.
4. Em **Project settings → General → Your apps**, selecione o aplicativo Web já registrado. As quatro variáveis públicas já estão presentes em `frontend/.env.local`; não as imprima nem sobrescreva durante a homologação. Se a configuração precisar ser refeita, use os campos públicos do aplicativo Web:

   | Campo da configuração Web | Variável |
   |---|---|
   | `apiKey` | `NEXT_PUBLIC_FIREBASE_API_KEY` |
   | `authDomain` | `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN` |
   | `projectId` | `NEXT_PUBLIC_FIREBASE_PROJECT_ID` |
   | `appId` | `NEXT_PUBLIC_FIREBASE_APP_ID` |

   `projectId` deve ser `prime-amulet-439718-e3`. Esses são campos públicos da aplicação Web, não credenciais Admin. Nunca use ou copie JSON de service account para o frontend.

## 2. Criar ou selecionar a conta

1. Em **Authentication → Users**, crie uma conta de teste com **Add user** no provedor habilitado ou procure o e-mail exato da conta existente que será o administrador.
2. Abra a linha dessa conta e copie o valor do campo **UID**. Confirme a identidade/posse da conta com a pessoa que fará o primeiro login. Use o UID, não o e-mail, no bootstrap.
3. Registre o UID para a operação local. Não atribua custom claims manualmente no Console.
4. A conta precisa existir antes do bootstrap. O utilitário não cria usuários nem organizações.

## 3. Preparar Application Default Credentials no Windows

O ADC local, o projeto de quota e o acesso de leitura do Firebase Admin SDK foram validados. O Google Cloud CLI está configurado no computador; use os comandos abaixo somente se precisar renovar o ADC. Não tente ler ou copiar o conteúdo do arquivo de credenciais.

Com uma conta Google autorizada a administrar usuários Firebase no projeto, execute interativamente apenas se for necessário renovar a autenticação:

```powershell
gcloud version
gcloud auth login
gcloud config set project prime-amulet-439718-e3
gcloud auth application-default login
```

O último comando abre o fluxo de login e grava ADC localmente. Para chamadas administrativas, a identidade precisa de permissão de listar, consultar e atualizar usuários Firebase Authentication no projeto. Se necessário e aprovado pelo responsável IAM, use o papel **Firebase Authentication Admin** (`roles/firebaseauth.admin`) ou um papel customizado mais restrito. O quota project já foi validado; se precisar configurá-lo novamente, faça-o somente com a permissão `serviceusage.services.use`:

```powershell
gcloud auth application-default set-quota-project prime-amulet-439718-e3
```

Esses comandos configuram autenticação local; não criam recursos de aplicação. Não execute o bootstrap até a conta, o tenant e as permissões serem confirmados. O `.env` do backend deve manter `FIREBASE_PROJECT_ID` e `GOOGLE_CLOUD_PROJECT` iguais ao projeto esperado; a validação do backend rejeita divergências.

## 4. Bootstrap administrativo

O bootstrap aprovado foi concluído para a conta existente do tenant `lead-intelligence-dev`. Uma consulta de leitura ao Firebase Admin SDK confirmou `role=admin` e `tenant_id=lead-intelligence-dev`. Não execute o comando novamente para essa conta.

O comando usado foi:

```powershell
uv run python -m backend.scripts.bootstrap_admin
```

Para um futuro tenant, um operador autorizado deve executar o comando em terminal interativo a partir da raiz do repositório, usando o UID confirmado da conta existente e o tenant aprovado. O comando recusa projeto divergente, tenant inválido, administrador já existente no tenant (ou administrador sem tenant) e conta que já tenha `role` ou `tenant_id`. Ele preserva claims não relacionados. Execute uma vez por tenant e por um único operador de cada vez.

O comando altera custom claims reais quando executado com ADC e IAM válidos. Após qualquer atribuição aprovada, o usuário deve entrar novamente para obter um ID token atualizado.

## 5. Checklist de validação real

- [x] As quatro variáveis Firebase Web estão presentes e o project ID coincide com `prime-amulet-439718-e3`; seus valores não foram exibidos.
- [x] Email/Password está habilitado e `localhost` consta nos domínios autorizados.
- [x] ADC e quota foram validados; `/api/health` responde `200`.
- [x] O bootstrap do administrador existente foi concluído e as claims esperadas foram confirmadas por consulta de leitura.
- [x] A sessão local mostra o perfil **Administrador**; `GET /api/dashboard` e `GET /api/imports` autenticados responderam `200`.
- [x] Uma planilha sintética foi pré-visualizada e confirmada; o dashboard refletiu um registro classificado como `research` no tenant esperado.
- [x] Chamadas sem token retornaram `401`; testes sintéticos confirmaram `403` em rotas exclusivas do auditor para a role admin.
- [x] Testes de integração sintéticos confirmaram isolamento de dashboard, histórico e confirmação de importações entre tenants.

Não copie ID tokens, ADC, senhas ou configuração privada em logs, issues ou mensagens. O dashboard administrativo contém apenas indicadores agregados e importações do tenant; o acesso a leads continua restrito à role `auditor`.
