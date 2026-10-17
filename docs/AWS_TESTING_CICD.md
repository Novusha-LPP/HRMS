# Testing branch → EC2 + Docker + RDS

Every push to **`testing`**, including a merged pull request, runs CI. Once the one-time
setup below is complete and `AWS_TESTING_ENABLED=true`, a successful run builds the API
and frontend, publishes them to ECR, and deploys them through Systems Manager (SSM).
Production is not connected to this workflow.

```text
push / merge → testing → isolated CI (PostgreSQL 18) → ECR images pinned by digest
                                                         ↓
                                   S3 deployment bundle → SSM → existing EC2
                                                         ↓
                             RDS preflight → migrations → API + jobs + web
                                                         ↓
                                  readiness + exact commit verification
```

The target supplied for this setup is AWS account **891377284307**, region **ap-south-1**,
EC2 instance **i-0d7abe00772ca6669**, RDS endpoint
`hrmstest.crgowckyse2b.ap-south-1.rds.amazonaws.com`. A connection to the default
`postgres` database proves network access; create a separate application database.

The workflow does not provision or alter the existing instance/RDS instance. The provided
CloudFormation template provisions deployment support resources only. No cloud resources
have been created merely by adding these files.

## 1. Prepare the application database

In the existing RDS `psql` session, as the migration owner:

```sql
CREATE DATABASE hrms_testing OWNER "Hrms";
SELECT current_user, rolsuper, rolbypassrls
FROM pg_roles WHERE rolname = current_user;
```

Run `CREATE DATABASE` only if that database does not already exist. The username `Hrms`
is case-sensitive in SQL, so keep its double quotes. The API connects as `hrms_app`, the
platform console as `hrms_platform`, and only the migration container uses `Hrms`.
Migrations create the two restricted roles and their schema privileges.

**RDS compatibility requirement:** this codebase's login/integration lookup functions run
as their owner and read tables with `FORCE ROW LEVEL SECURITY`. RDS administrators are
not ordinary PostgreSQL superusers. Before touching persistent schema, the deployment
runs a temporary-table probe as the migration owner to verify that the current owner can
read through forced RLS. If it cannot, the deployment stops and existing services remain
running. Resolve the migration owner's RDS privileges before enabling automatic deployment.
If RDS cannot provide the required owner behavior, a policy-based compatibility change
and tenant-isolation regression tests are needed; that change is not included here.
Do not grant `hrms_app` or `hrms_platform` superuser/BYPASSRLS privileges or disable tenant RLS.
See [AWS's administrator-role documentation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Roles.rds_superuser.html)
and [PostgreSQL RLS behavior](https://www.postgresql.org/docs/current/ddl-rowsecurity.html).

CI uses disposable PostgreSQL 18 databases to match the RDS major version. It never runs
backend tests against this shared RDS instance. The existing self-contained Docker smoke
test additionally continues to test its PostgreSQL 16 stack.

Your `psql` 15 client can make basic connections to server 18. Use PostgreSQL 18 client
tools for backup/restore work: an older `pg_dump` refuses a newer server.
See [pg_dump version compatibility](https://www.postgresql.org/docs/current/app-pgdump.html).

## 2. Create deployment support resources

From an authenticated AWS administrator terminal, in this repository:

```bash
aws sts get-caller-identity
aws iam list-open-id-connect-providers
aws cloudformation deploy \
  --region ap-south-1 \
  --stack-name hrms-testing-cicd \
  --template-file deploy/aws/bootstrap.yml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides InstanceId=i-0d7abe00772ca6669 CreateGitHubOidcProvider=false

aws cloudformation describe-stacks \
  --region ap-south-1 --stack-name hrms-testing-cicd \
  --query 'Stacks[0].Outputs' --output table
```

Verify that `get-caller-identity` reports account `891377284307`. If this account has no
OIDC provider for `token.actions.githubusercontent.com`, change
`CreateGitHubOidcProvider=true`. If it already exists, keep `false`.

The template creates two private ECR repositories with immutable tags, an encrypted private
S3 artifact bucket, a GitHub deployment role, and an EC2 instance profile. Its deployment
permissions target the specified instance and repositories. ECR repositories and the
artifact bucket are retained if the stack is deleted. Storage and image scan costs apply;
remove unused images/bundles according to your retention requirements.

If those ECR repository names already exist, supply new `ApiRepositoryName` and
`WebRepositoryName` parameters and use the resulting names in GitHub.

In **EC2 → Instances → i-0d7abe00772ca6669 → Actions → Security → Modify IAM role**, attach
the `EC2InstanceProfile` from the stack output. If the instance already has an application
IAM role, preserve its permissions and add the equivalent SSM/ECR/S3 permissions from the
template to that role instead of replacing it blindly. The supplied instance role has no
application-document-bucket access; add narrowly scoped S3 permissions if you select S3
document storage.

The instance must appear **Online** in Systems Manager. SSM Agent and the AWS CLI must be
installed. It needs outbound HTTPS to SSM, ECR, and S3 via internet/NAT or suitable VPC
endpoints. CI does not need SSH ingress or direct RDS access.
See [SSM instance permissions](https://docs.aws.amazon.com/systems-manager/latest/userguide/setup-instance-permissions.html).

## 3. Prepare EC2 once

Install Docker Engine, the Docker Compose plugin **2.30 or newer**, AWS CLI, Python 3,
`curl`, `tar`, `flock`, and the usual core utilities for the instance's Linux distribution.
Enable Docker and SSM Agent at boot. Check:

```bash
uname -m
sudo docker version
sudo docker compose version
aws --version
aws sts get-caller-identity
sudo systemctl status amazon-ssm-agent --no-pager
```

For `uname -m = x86_64`, use `EC2_IMAGE_PLATFORM=linux/amd64`; for `aarch64`, use
`linux/arm64`. The RDS server's ARM architecture does not determine the EC2 image architecture.
If application containers use the EC2 role for S3/SES, configure IMDSv2 with a response hop
limit of 2 so the container bridge can reach the instance credentials. Avoid static AWS keys.

Create the configuration directory and install the CA bundle:

```bash
sudo install -d -m 700 /etc/hrms
sudo install -d -m 700 /opt/hrms/testing/releases
curl --fail --silent --show-error \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
  -o /tmp/hrms-rds-global-bundle.pem
sudo install -m 644 /tmp/hrms-rds-global-bundle.pem /etc/hrms/rds-global-bundle.pem
```

Create these **root-owned mode 600** files from the supplied examples. Edit them locally
on EC2 with `sudoedit`, then set their permissions. They are not GitHub secrets and must
never be committed or copied into the deployment bundle.

| Example in this repository | Destination on EC2 | Who receives it |
|---|---|---|
| `deploy/aws/testing.runtime.env.example` | `/etc/hrms/testing.runtime.env` | API, jobs, migration |
| `deploy/aws/testing.migrate.env.example` | `/etc/hrms/testing.migrate.env` | Migration only |
| `deploy/aws/testing.deploy.env.example` | `/etc/hrms/testing.deploy.env` | Compose public settings |

```bash
sudo chown root:root /etc/hrms/testing.*.env
sudo chmod 600 /etc/hrms/testing.*.env
openssl rand -hex 32
python3 -c "import os,base64; print('k1:'+base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Run `openssl rand -hex 32` separately for each database role password, signing secret, and
metrics token. Runtime and migration role passwords must match. URL-encode the existing
owner password in its connection URL. Use literal values without shell quotes or `export`.
Keep a separate recovery copy of `HRMS_FIELD_ENCRYPTION_KEYS`; losing it loses encrypted data.

All three database URLs use **`?ssl=verify-full`**. The containers mount the RDS CA bundle
and set `PGSSLROOTCERT`. Do not use the libpq `sslmode` query parameter in SQLAlchemy's
asyncpg URL. See [RDS TLS verification](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html).

## 4. Route HTTPS traffic and protect RDS

The defaults publish API port **8115** and web port **8180** to loopback. Configure your
host HTTPS reverse proxy or Cloudflare tunnel to forward the public API and frontend
hostnames to those ports. The examples use the hostnames already documented in this repo:

```text
https://testinghrms.alvision.in → http://127.0.0.1:8180
https://hrmsapi.alvision.in     → http://127.0.0.1:8115
```

Replace these domains in both configuration files if the AWS test environment uses other
names. `HRMS_WEB_API_URL` is the API's HTTPS origin, without `/v1` or a trailing slash.
The frontend's HTTPS origin must appear in `HRMS_CORS_ORIGINS`.

For an ALB, set `HRMS_BIND_ADDRESS=0.0.0.0`, allow EC2 ports 8115/8180 **only from the ALB
security group**, use an ACM HTTPS listener, and configure API health checks on
`/health/ready` and frontend checks on `/healthz`. Configure forwarded-header trust to match
the actual proxy source ranges observed inside the container; do not use `*`. Restrict
public API routing to application and health routes; keep `/metrics` private.

RDS should remain private, with inbound PostgreSQL 5432 allowed only from the EC2 security
group. The Docker subnet `172.30.25.0/24` must not overlap your VPC/other container networks.
Enable RDS automated backups/PITR. Uploaded documents also need backups: either back up
the persistent `hrms-testing-aws_kyc-storage` volume or use a private versioned S3 document
bucket. RDS backups do not include uploaded files or application encryption keys.

## 5. Configure GitHub

In [Novusha-LPP/HRMS](https://github.com/Novusha-LPP/HRMS), create the GitHub **environment**
named **`testing`**. Restrict its deployment branches to **`testing`**. Do not add required
reviewers if you want each successful push to deploy immediately.

Add these **environment variables** under `testing`:

| Variable | Value |
|---|---|
| `AWS_REGION` | `ap-south-1` |
| `AWS_ROLE_ARN` | Stack output `AWSRoleArn` |
| `EC2_INSTANCE_ID` | `i-0d7abe00772ca6669` |
| `DEPLOY_ARTIFACT_BUCKET` | Stack output `ArtifactBucketName` |
| `ECR_API_REPOSITORY` | `hrms-testing-api` or stack output |
| `ECR_WEB_REPOSITORY` | `hrms-testing-web` or stack output |
| `EC2_IMAGE_PLATFORM` | `linux/amd64` or `linux/arm64` from EC2 `uname -m` |

AWS authentication uses GitHub OIDC. No `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
database password, or EC2 SSH key is needed in GitHub. The default trust subject is
`repo:Novusha-LPP/HRMS:environment:testing`. Repositories created after July 15, 2026, or
opted into immutable subjects use a subject containing owner/repository IDs; pass the
actual subject as the stack's `GitHubOidcSubject` parameter if applicable.
See [GitHub AWS OIDC configuration](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).

Once the host, database owner, HTTPS routing, and IAM configuration are ready, add the
**repository variable** `AWS_TESTING_ENABLED=true`. Until then, testing CI runs and the
deployment job is skipped. This is a one-time enable switch, not a per-deployment approval.

## 6. Activate and use the branch

The branch name is **`testing`**. Commit the deployment files and publish the branch:

```bash
git push -u origin testing
```

After setup, a push to `testing` runs **Deploy testing to EC2**. A merged PR produces the
same push event. It runs the existing backend/frontend/browser/smoke checks, builds the
exact checked commit, uploads a checksummed script bundle to private S3, and waits for
SSM to report successful migrations, readiness, and commit verification. Deployment does
not run for another branch or for an unmerged PR. The existing main release workflow is
separate and is not used for EC2 testing deployments.

Use **Actions → an existing Deploy testing to EC2 run → Re-run all jobs** to retry a run.
The optional **Run workflow** button becomes available once this workflow also exists on
the repository's default branch; select `testing` when using it. Protect `testing` with required CI checks and pull requests
if you want changes reviewed before deployment. Avoid force pushes.

The pipeline serializes deployments and the instance also uses a deployment lock. GitHub
may coalesce pending runs during rapid pushes, so intermediate commits are not guaranteed
their own deployment. Failed checks do not publish or deploy. A failed migration leaves
the running service images alone, although earlier completed migrations may already have
been applied. If new services fail health checks, the script attempts to restore the
previous service images; this requires backward-compatible migrations.

## Verification and rollback

After the first successful deployment, verify the HTTPS frontend, tenant sign-in,
platform sign-in, document upload/download, and scheduled jobs. Readiness confirms RDS
and schema access; it does not replace a real authentication check.

On EC2:

```bash
sudo readlink -f /opt/hrms/testing/current
sudo docker ps --filter name=hrms-testing-aws
curl --fail http://127.0.0.1:8115/health/ready
curl --fail http://127.0.0.1:8180/healthz
```

Actions reports the SSM command ID. Inspect failures in the AWS SSM Run Command console;
the workflow deliberately does not copy container logs into GitHub. Configure CloudWatch
or your existing monitoring for availability, container restarts, RDS resources, and stale
jobs. Docker logs rotate locally.

For a **code-only** rollback, select the previous healthy release directory under
`/opt/hrms/testing/releases` and run:

```bash
sudo bash /opt/hrms/testing/releases/PREVIOUS_RELEASE/deploy.sh \
  /opt/hrms/testing/releases/PREVIOUS_RELEASE --code-only
```

This restores API/web/job images without running migrations or downgrading the schema.
Keep release directories and corresponding images for your rollback window. Do not rotate
role passwords/encryption keys as part of a routine release. A breaking schema change needs
its own recovery plan and an RDS restore rehearsal.

Later, production can use a separate environment, instance, database, IAM role, and an
explicit promotion workflow. Do not point this testing configuration at production.
