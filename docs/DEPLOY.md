# Pôr online (Oracle Cloud Always Free)

Resultado: o site em `https://<ip-com-traços>.sslip.io`, com HTTPS automático, a recolher
dados 24 h por dia. Custo: **0 €**, dentro dos limites Always Free (VM ARM até 4 OCPU / 24 GB).

```
Internet ──443──▶ Caddy (HTTPS, cabeçalhos, CSP) ──▶ web (FastAPI + React)
                                                    │
        coletor ─▶ Redpanda ─▶ ingestor / motor de atrasos ─▶ TimescaleDB
```

Só as portas 80 e 443 ficam abertas à Internet. A base de dados e o Redpanda só são
acessíveis de dentro da própria VM.

## 1. Criar a VM (≈ 5 min na consola)

1. Crie conta em [cloud.oracle.com](https://cloud.oracle.com) (Free Tier). A Oracle pede um cartão para verificação, mas não cobra nada dentro dos limites Always Free.
2. **Compute → Instances → Create instance**:
   - **Name:** `cmlive`
   - **Image:** *Canonical Ubuntu 24.04*
   - **Shape:** *Ampere* → `VM.Standard.A1.Flex`, **2 OCPU, 12 GB** de memória
   - **Networking:** crie uma VCN nova com sub-rede **pública** e deixe *Assign a public IPv4 address* ligado
   - **SSH keys:** descarregue a chave privada (precisa dela para manutenção)
   - **Show advanced options → Management → Paste cloud-init script:** cole o conteúdo de
     [`deploy/cloud-init.yaml`](../deploy/cloud-init.yaml)
3. **Create.**

## 2. Abrir as portas 80 e 443 (obrigatório)

A rede da Oracle bloqueia tudo exceto SSH. Sem este passo, o site não abre e o
certificado HTTPS não é emitido (o Let's Encrypt precisa da porta 80).

**Networking → Virtual cloud networks →** a sua VCN **→ Subnets →** a sub-rede pública
**→ Security Lists → Default Security List → Add Ingress Rules**, duas vezes:

| Source CIDR | IP Protocol | Destination Port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

A firewall dentro da VM (iptables) é aberta pelo script de instalação.

## 3. Esperar e abrir

A instalação corre sozinha no primeiro arranque e demora **10 a 15 minutos**, sobretudo
pelo *build* da imagem. Depois:

- Site: `https://<IP-com-traços>.sslip.io`. Por exemplo, o IP `203.0.113.10` dá
  `https://203-0-113-10.sslip.io`.
- O endereço exato fica no fim do log de instalação e em `/opt/cmlive/.env`.

Para acompanhar a instalação:

```bash
ssh -i chave.key ubuntu@<IP>
sudo tail -f /var/log/cloud-init-output.log        # progresso da instalação
cd /opt/cmlive
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml ps
sudo docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml logs -f --tail=50 collector web
```

## Manutenção

| Tarefa | Comando (na VM) |
|---|---|
| Atualizar para a versão mais recente do `main` | `sudo bash /opt/cmlive/deploy/install.sh` |
| Ver o estado | `cd /opt/cmlive && sudo docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml ps` |
| GTFS | Atualizado todos os dias às 05:17 (cron); só recarrega se o ficheiro mudou |
| Usar um domínio próprio | Crie um registo DNS `A` para o IP, mude `SITE_ADDRESS` em `/opt/cmlive/.env` e corra o `install.sh` |

## Problemas comuns

- **"Out of capacity for shape VM.Standard.A1.Flex".** Há falta de máquinas ARM gratuitas
  nessa zona. Tente outro *Availability Domain*, mais tarde, ou com 1 OCPU / 6 GB.
- **O site não abre, ou não há certificado.** Quase sempre é o passo 2 (Security List).
  Confirme também que a sub-rede é pública e que a VM tem IP público.
- **A instância foi parada pela Oracle.** As instâncias Always Free podem ser recuperadas se
  ficarem "inativas" durante 7 dias (CPU, rede e memória abaixo de 20% no percentil 95). Este
  projeto é leve e pode cair nesse critério. A solução oficial é passar a conta a
  *Pay As You Go*, que continua gratuita dentro dos limites Always Free e não está sujeita a
  esta recuperação.
- **"toomanyrequests" do Docker Hub durante o *build*.** É o limite de downloads anónimos por
  IP. Espere uns minutos e corra o `install.sh` outra vez.

## O que não está incluído

- **Backups da BD.** Os dados ficam em volumes Docker na própria VM. Para um projeto de
  portefólio chega; para algo sério, usar `pg_dump` periódico para *object storage*.
- **Alta disponibilidade.** É uma única VM.
