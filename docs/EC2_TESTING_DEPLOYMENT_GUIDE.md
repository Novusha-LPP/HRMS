# Complete End-to-End Runbook: Deploying HRMS Testing to EC2

This guide is the complete, self-contained operational runbook for deploying the **`testing`** branch of HRMS to an AWS EC2 instance backed by AWS RDS PostgreSQL, orchestrated securely through GitHub Actions and AWS Systems Manager (SSM).

---

## 1. Architecture & Pipeline Overview

```text
git push origin testing
       │
       ▼
GitHub Actions (.github/workflows/deploy-testing-ec2.yml)
  ├── 1. deployment-config: runs unittests & isolated host failure scenarios in Docker
  ├── 2. checks: runs isolated backend tests, migrations & frontend tests on PostgreSQL 18
  └── 3. deploy:
        ├── Assumes IAM Deploy Role via GitHub OIDC (no static AWS keys)
        ├── Builds Docker images for API and Web (pinned with GIT_SHA & commit metadata)
        ├── Pushes immutable images to Amazon ECR (hrms-testing-api, hrms-testing-web)
        ├── Packages deployment bundle (compose.yml, deploy.sh, validate.py, database-preflight.py, images.json)
        ├── Uploads checksummed tar.gz bundle to private Amazon S3 artifact bucket
        └── Dispatches AWS SSM Run Command to the EC2 instance and streams progress
                │
                ▼ (SSM on EC2 instance i-0d7abe00772ca6669)
         EC2 Host Deployment (/opt/hrms/testing/releases/<SHA>-<RUN_ID>-<ATTEMPT>)
           ├── Checks file lock /opt/hrms/testing/deploy.lock (prevents concurrent deploys)
           ├── Validates mode 600 env files in /etc/hrms/ (validate.py)
           ├── Verifies ECR image digests and generates images.env
           ├── Authenticates Docker to ECR and pulls images
           ├── Runs database-preflight.py (verifies RDS TLS & migration owner RLS permissions)
           ├── Executes Alembic migrations & rotates app/platform role passwords (python -m hrms.deploy migrate)
           ├── Starts/updates api, jobs, and web services with Compose (--wait --wait-timeout 180)
           ├── Queries container http://127.0.0.1:8015/health to verify running commit matches Git SHA
           └── Atomically updates symlink /opt/hrms/testing/current -> release directory
```

### Target Infrastructure Reference

| Component | Target Setting |
|---|---|
| **AWS Account ID** | `891377284307` |
| **AWS Region** | `ap-south-1` (Mumbai) |
| **EC2 Instance ID** | `i-0d7abe00772ca6669` |
| **RDS PostgreSQL Endpoint** | `hrmstest.crgowckyse2b.ap-south-1.rds.amazonaws.com:5432` |
| **Application Database** | `hrms_testing` |
| **Database Migration Owner** | `Hrms` (case-sensitive in SQL) |
| **Restricted Runtime Roles** | `hrms_app`, `hrms_platform` (created/managed by migrations) |
| **API Loopback Port** | `127.0.0.1:8115` (mapped to container port `8015`) |
| **Frontend Loopback Port** | `127.0.0.1:8180` (mapped to container port `8080`) |
| **Public Frontend Domain** | `https://testinghrms.alvision.in` |
| **Public API Domain** | `https://hrmsapi.alvision.in` |

---

## 2. Phase 1: RDS Database & RLS Preparation

Connect to your existing RDS PostgreSQL instance from an authenticated terminal (e.g. from EC2 or an administrative bastion):

```bash
psql -h hrmstest.crgowckyse2b.ap-south-1.rds.amazonaws.com -p 5432 -U Hrms -d postgres
```

Inside `psql`, execute the following SQL:

```sql
-- 1. Create the dedicated testing application database (if not already existing)
CREATE DATABASE hrms_testing OWNER "Hrms";

-- 2. Switch to the newly created database
\c hrms_testing

-- 3. CRITICAL: Grant BYPASSRLS to the migration owner "Hrms"
-- HRMS tables enforce FORCE ROW LEVEL SECURITY. User login lookup queries execute as
-- owner-owned SECURITY DEFINER functions BEFORE a tenant context is set.
-- If the migration owner lacks BYPASSRLS, login lookups return 0 rows for all users.
ALTER ROLE "Hrms" WITH BYPASSRLS;

-- 4. Verify that rolbypassrls is true:
SELECT rolname, rolsuper, rolbypassrls
FROM pg_roles
WHERE rolname = 'Hrms';
```

> [!IMPORTANT]
> The automated deployment runs `deploy/aws/database-preflight.py` before applying any migrations. It probes whether the migration owner can read through forced RLS on a temporary table. If `rolbypassrls` is `false`, the deployment safely aborts and previous containers remain online.

---

## 3. Phase 2: Deploy AWS Deployment Support Stack (CloudFormation)

The repository provides a complete CloudFormation template at `deploy/aws/bootstrap.yml`. It provisions:
- Two private Amazon ECR repositories (`hrms-testing-api`, `hrms-testing-web`) with tag immutability and scan-on-push.
- An encrypted, versioned Amazon S3 artifact bucket for deployment bundles.
- A GitHub OIDC IAM Role scoped strictly to repository `Novusha-LPP/HRMS` and environment `testing`.
- An EC2 Instance Profile with least-privilege permissions to pull ECR images, download release bundles from S3, and interact with AWS SSM.

### 1. Deploy the CloudFormation Stack

From an AWS administrator terminal (AWS CLI authenticated to account `891377284307`):

```bash
# Verify caller identity
aws sts get-caller-identity --query Account --output text

# Deploy the stack in ap-south-1
aws cloudformation deploy \
  --region ap-south-1 \
  --stack-name hrms-testing-cicd \
  --template-file deploy/aws/bootstrap.yml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      InstanceId=i-0d7abe00772ca6669 \
      CreateGitHubOidcProvider=false
```

*(Note: If the AWS account does not already have an IAM OIDC provider for `token.actions.githubusercontent.com`, set `CreateGitHubOidcProvider=true`)*.

### 2. Retrieve Stack Outputs

```bash
aws cloudformation describe-stacks \
  --region ap-south-1 \
  --stack-name hrms-testing-cicd \
  --query 'Stacks[0].Outputs' \
  --output table
```

Record the following outputs:
- **`AWSRoleArn`**: (e.g. `arn:aws:iam::891377284307:role/hrms-testing-cicd-GitHubDeployRole-...`)
- **`ArtifactBucketName`**: (e.g. `hrms-testing-cicd-artifactbucket-...`)
- **`ApiRepositoryName`**: `hrms-testing-api`
- **`WebRepositoryName`**: `hrms-testing-web`
- **`EC2InstanceProfile`**: (e.g. `hrms-testing-cicd-InstanceProfile-...`)

### 3. Attach the IAM Instance Profile to EC2

Attach the instance profile to `i-0d7abe00772ca6669`:
- **AWS Console**: Navigate to **EC2 → Instances → `i-0d7abe00772ca6669` → Actions → Security → Modify IAM role**, select the `EC2InstanceProfile` created above, and click **Update IAM role**.
- **Or via AWS CLI**:
  ```bash
  aws ec2 associate-iam-instance-profile \
    --instance-id i-0d7abe00772ca6669 \
    --iam-instance-profile Name=<EC2InstanceProfileName>
  ```

---

## 4. Phase 3: EC2 Host Setup (One-Time Configuration)

SSH into the target EC2 instance:

```bash
ssh -i /path/to/key.pem ubuntu@<EC2_PUBLIC_IP_OR_DNS>
```

### 1. Verify Host Prerequisites

The host requires Docker Engine, Docker Compose v2.30+, AWS CLI, Python 3, and the Amazon SSM Agent:

```bash
uname -m                                      # x86_64 -> linux/amd64, aarch64 -> linux/arm64
sudo docker version
sudo docker compose version                   # Must be 2.30 or newer
aws --version
sudo systemctl status amazon-ssm-agent --no-pager
```

If any packages are missing:
```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 awscli python3 curl tar
sudo systemctl enable --now docker amazon-ssm-agent
```

### 2. Create Required Directories and Install the RDS CA Bundle

```bash
sudo install -d -m 700 /etc/hrms
sudo install -d -m 700 /opt/hrms/testing/releases

# Download and install AWS RDS Global CA certificate bundle
curl --fail --silent --show-error \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
  -o /tmp/hrms-rds-global-bundle.pem
sudo install -m 644 /tmp/hrms-rds-global-bundle.pem /etc/hrms/rds-global-bundle.pem
```

### 3. Generate Encryption Secrets & Role Passwords

Generate cryptographically secure secrets on the EC2 host:

```bash
# Generate 4 distinct random hex strings for passwords and tokens:
openssl rand -hex 32  # Save as APP_ROLE_PASSWORD
openssl rand -hex 32  # Save as PLATFORM_ROLE_PASSWORD
openssl rand -hex 32  # Save as HRMS_SECRET_KEY
openssl rand -hex 32  # Save as HRMS_METRICS_TOKEN

# Generate AES-256 field encryption key (URL-safe base64):
python3 -c "import os,base64; print('k1:'+base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

### 4. Create the Mode 600 Environment Files in `/etc/hrms/`

These files live exclusively on the EC2 host. They are never checked into Git or copied into GitHub Actions.

#### File 1: `/etc/hrms/testing.runtime.env`
Create with `sudoedit /etc/hrms/testing.runtime.env`:

```ini
# /etc/hrms/testing.runtime.env (Mode 600, root:root)
# Note: Ensure passwords in URLs are percent-encoded if they contain special characters.
HRMS_DATABASE_URL=postgresql+asyncpg://hrms_app:YOUR_APP_ROLE_PASSWORD@hrmstest.crgowckyse2b.ap-south-1.rds.amazonaws.com:5432/hrms_testing?ssl=verify-full
HRMS_APP_DATABASE_URL=postgresql+asyncpg://hrms_app:YOUR_APP_ROLE_PASSWORD@hrmstest.crgowckyse2b.ap-south-1.rds.amazonaws.com:5432/hrms_testing?ssl=verify-full
HRMS_PLATFORM_DATABASE_URL=postgresql+asyncpg://hrms_platform:YOUR_PLATFORM_ROLE_PASSWORD@hrmstest.crgowckyse2b.ap-south-1.rds.amazonaws.com:5432/hrms_testing?ssl=verify-full

HRMS_SECRET_KEY=YOUR_64_HEX_CHARACTERS_SECRET_KEY
HRMS_METRICS_TOKEN=YOUR_64_HEX_CHARACTERS_METRICS_TOKEN
HRMS_FIELD_ENCRYPTION_KEYS=k1:YOUR_GENERATED_BASE64_KEY

HRMS_CORS_ORIGINS=https://testinghrms.alvision.in
HRMS_ALLOW_PUBLIC_REGISTRATION=false
HRMS_API_DOCS_ENABLED=false
HRMS_DATABASE_POOL_SIZE=5
HRMS_DATABASE_MAX_OVERFLOW=5
HRMS_DEFAULT_TIMEZONE=Asia/Kolkata
HRMS_JOBS_DAILY_AT=00:30
WEB_CONCURRENCY=2
HRMS_DOCUMENT_STORAGE=local
HRMS_MAIL_BACKEND=disabled
```

#### File 2: `/etc/hrms/testing.migrate.env`
Create with `sudoedit /etc/hrms/testing.migrate.env`:

```ini
# /etc/hrms/testing.migrate.env (Mode 600, root:root)
# Used only by the ephemeral migration container to execute Alembic and role privilege setup.
HRMS_DATABASE_URL=postgresql+asyncpg://Hrms:YOUR_RDS_OWNER_PASSWORD@hrmstest.crgowckyse2b.ap-south-1.rds.amazonaws.com:5432/hrms_testing?ssl=verify-full
HRMS_APP_ROLE_PASSWORD=YOUR_APP_ROLE_PASSWORD
HRMS_PLATFORM_ROLE_PASSWORD=YOUR_PLATFORM_ROLE_PASSWORD
```

#### File 3: `/etc/hrms/testing.deploy.env`
Create with `sudoedit /etc/hrms/testing.deploy.env`:

```ini
# /etc/hrms/testing.deploy.env (Mode 600, root:root)
HRMS_WEB_API_URL=https://hrmsapi.alvision.in
HRMS_API_PORT=8115
HRMS_WEB_PORT=8180
HRMS_BIND_ADDRESS=127.0.0.1
HRMS_FORWARDED_ALLOW_IPS=172.30.25.1
HRMS_API_MEMORY=1g
```

#### Set Strict Permissions:
```bash
sudo chown root:root /etc/hrms/testing.*.env
sudo chmod 600 /etc/hrms/testing.*.env
ls -la /etc/hrms/
```

### 5. Configure Reverse Proxy / Port Forwarding

The application binds to loopback ports:
- **`8180`**: Nginx frontend serving the React single-page application.
- **`8115`**: FastAPI backend API serving `/v1` endpoints and `/health`.

Configure your host Nginx, Caddy, or Cloudflare Tunnel:
```text
https://testinghrms.alvision.in  ──▶  http://127.0.0.1:8180
https://hrmsapi.alvision.in      ──▶  http://127.0.0.1:8115
```

If using an AWS Application Load Balancer (ALB):
- Set `HRMS_BIND_ADDRESS=0.0.0.0` in `/etc/hrms/testing.deploy.env`.
- Restrict EC2 Security Group ingress on 8115 and 8180 strictly to the ALB Security Group.
- ALB Health Check paths:
  - Target Group API (8115): `/health/ready`
  - Target Group Web (8180): `/healthz`

---

## 5. Phase 4: GitHub Repository & Environment Configuration

In GitHub: [Novusha-LPP/HRMS](https://github.com/Novusha-LPP/HRMS):

### 1. Create the `testing` Environment
1. Go to **Settings → Environments → New environment**.
2. Name the environment **`testing`**.
3. Under **Deployment branches and tags**, select **Selected branches** and add the rule **`testing`**.
4. (Do not add required reviewers if you want pushes to deploy immediately).

### 2. Add Environment Secrets under `testing`
Inside the `testing` environment, click **Add environment secret** to supply the application and database credentials. The deployment workflow validates these and installs them to `/etc/hrms/` on EC2 automatically:

| Secret Name | Description | Example / Recommended Format |
|---|---|---|
| `RDS_OWNER_PASSWORD` | Master password for PostgreSQL user `Hrms` | Existing RDS master password |
| `HRMS_APP_ROLE_PASSWORD` | Password for restricted `hrms_app` DB role | `openssl rand -hex 32` |
| `HRMS_PLATFORM_ROLE_PASSWORD` | Password for restricted `hrms_platform` DB role | `openssl rand -hex 32` |
| `HRMS_SECRET_KEY` | 64-hex char JWT / session signing key | `openssl rand -hex 32` |
| `HRMS_METRICS_TOKEN` | Bearer token protecting `GET /metrics` | `openssl rand -hex 32` |
| `HRMS_FIELD_ENCRYPTION_KEYS` | AES-256 key for field-level PII encryption | `k1:<base64url 32 bytes>` (e.g. `python3 -c "import os,base64; print('k1:'+base64.urlsafe_b64encode(os.urandom(32)).decode())"`) |

### 3. Add Environment Variables under `testing`
Inside the `testing` environment, click **Add environment variable**:

| Variable Name | Default / Value | Description |
|---|---|---|
| `AWS_REGION` | `ap-south-1` | AWS deployment region |
| `AWS_ROLE_ARN` | `arn:aws:iam::891377284307:role/...` | `AWSRoleArn` from CloudFormation output |
| `EC2_INSTANCE_ID` | `i-0d7abe00772ca6669` | Target EC2 instance |
| `DEPLOY_ARTIFACT_BUCKET` | *(from CloudFormation output)* | S3 bucket for release bundles |
| `ECR_API_REPOSITORY` | `hrms-testing-api` | ECR repository for API |
| `ECR_WEB_REPOSITORY` | `hrms-testing-web` | ECR repository for Frontend |
| `EC2_IMAGE_PLATFORM` | `linux/amd64` (or `linux/arm64`) | Matching EC2 `uname -m` |
| `RDS_HOSTNAME` | `hrmstest.crgowckyse2b.ap-south-1.rds.amazonaws.com` | (Optional) RDS endpoint |
| `RDS_DATABASE` | `hrms_testing` | (Optional) Application database |
| `RDS_OWNER_USERNAME` | `Hrms` | (Optional) Master username |
| `HRMS_WEB_API_URL` | `https://hrmsapi.alvision.in` | (Optional) Public API origin |
| `HRMS_CORS_ORIGINS` | `https://testinghrms.alvision.in` | (Optional) Public Frontend origin |
| `HRMS_DOCUMENT_S3_BUCKET` | *(from CloudFormation output)* | S3 bucket for uploaded employee & recruitment documents |
| `HRMS_DOCUMENT_S3_REGION` | `ap-south-1` | AWS region where the document bucket resides |

### 4. Enable Deployment Workflow
In GitHub repository settings:
1. Go to **Settings → Secrets and variables → Actions → Variables** tab (Repository variables).
2. Click **New repository variable**.
3. Name: **`AWS_TESTING_ENABLED`**
4. Value: **`true`**

---

## 6. Amazon S3 Document Storage & User Data Isolation

The HRMS application stores all uploaded binary documents (KYC identity documents and recruitment candidate resumes) in Amazon S3 when `HRMS_DOCUMENT_STORAGE=s3` is configured.

### 1. How User Data is Isolated and Structured in S3

Files in S3 are organized with strict tenant and user/candidate path partitioning:

```text
s3://<DocumentBucket>/
├── kyc/
│   └── <tenant_id>/
│       └── <doc_id>_<clean_file_name>       # Employee KYC proof (Aadhaar, PAN, Passport)
└── recruitment/
    └── <tenant_id>/
        └── <candidate_id>/
            └── <uuid>_<clean_file_name>     # Candidate resume / CV
```

The database (PostgreSQL RDS) does **not** store binary files. It only stores an opaque reference `doc:<storage_key>` in the `storage_path` column of the `employee_kyc_documents` or `candidates` table.

### 2. Multi-Layered Security & User Isolation Guarantees

| Security Layer | Implementation Mechanism | User Privacy Guarantee |
|---|---|---|
| **1. Application AEAD Pre-Encryption** | Client-side AES-256-GCM encryption ([core/document_store.py](file:///home/aiserver/HRMS/backend/src/hrms/core/document_store.py)) using `HRMS_FIELD_ENCRYPTION_KEYS`. | Every file is encrypted **before** transmission to S3. The exact storage path (`kyc/{tenant_id}/{doc_id}_{filename}`) is passed as Associated Authenticated Data (AAD). If a blob is copied or swapped between users/tenants in S3, **AEAD authentication fails and the file will not decrypt**. |
| **2. AWS S3 Server-Side Encryption (SSE)** | `ServerSideEncryption="AES256"` (SSE-S3) on every `put_object`. | The S3 bucket never holds a plaintext byte at rest. |
| **3. Private, Non-Public Bucket** | `BlockPublicAcls`, `BlockPublicPolicy`, `IgnorePublicAcls`, `RestrictPublicBuckets` enabled in [deploy/aws/bootstrap.yml](file:///home/aiserver/HRMS/deploy/aws/bootstrap.yml). | No direct public access or presigned URLs are exposed to the internet. |
| **4. In-Transit Transport Security** | S3 Bucket Policy explicitly denies any non-TLS (`aws:SecureTransport: "false"`) requests. | All uploads and downloads are encrypted via TLS 1.3 / 1.2 in transit. |
| **5. Database Row-Level Security (RLS)** | PostgreSQL `FORCE ROW LEVEL SECURITY` on document tables. | Tenant isolation is enforced at the database kernel level; one tenant's queries can never query another tenant's document records. |
| **6. User Ownership & Scope Authorization** | KYC documents: employees can only view their own uploads (`user.employment_id == doc.employment_id`). Admins/HR require `kyc.verify` or `kyc.write` scope. Recruitment resumes: scoped to authorized hiring managers/recruiters. | Standard users cannot download or view documents belonging to another employee. |
| **7. Access Audit Logging** | Every view or download of KYC documents triggers an immutable audit log (`_log_access`) in PostgreSQL recording who viewed the document, timestamp, and IP. | Complete compliance traceability for sensitive identity documents. |

### 3. Enabling S3 Storage on EC2

To enable S3 document storage:
1. Ensure the `DocumentBucket` is provisioned using [deploy/aws/bootstrap.yml](file:///home/aiserver/HRMS/deploy/aws/bootstrap.yml) and the EC2 `InstanceProfile` is attached.
2. Ensure Docker containers on EC2 can reach the instance metadata service by setting the IMDSv2 hop limit to 2:
   ```bash
   aws ec2 modify-instance-metadata-options \
     --instance-id i-0d7abe00772ca6669 \
     --http-put-response-hop-limit 2 \
     --http-tokens required
   ```
3. Set `HRMS_DOCUMENT_S3_BUCKET` to your bucket name in GitHub Environment Variables (`testing`). The deployment pipeline automatically sets `HRMS_DOCUMENT_STORAGE=s3`, `HRMS_DOCUMENT_S3_BUCKET`, and `HRMS_DOCUMENT_S3_REGION`.

---

## 7. Phase 5: Triggering and Monitoring Deployments

### 1. Trigger the Deployment

The deployment pipeline triggers automatically whenever code is pushed to branch **`testing`**:

```bash
git push -u origin testing
```

You can also manually trigger a run from GitHub Actions:
- Go to **Actions → Deploy testing to EC2 → Run workflow → Branch: testing**.

### 2. Workflow Execution Stages

1. **`deployment-config` job**:
   - Executes `python3 -m unittest discover -s deploy/aws/tests -v`.
   - Runs syntax check `bash -n deploy/aws/deploy.sh`.
   - Runs `deploy/aws/tests/host_script_scenarios.py` inside an isolated container to verify rollback behaviors.
2. **`checks` job**:
   - Runs isolated backend Ruff, Mypy, dependency audits, Alembic upgrade/downgrade boundary checks, and full Pytest coverage on PostgreSQL 18.
   - Runs frontend linting, tests, and production build.
3. **`deploy` job**:
   - Authenticates to AWS via GitHub OIDC.
   - Builds API & Web Docker images and pushes them with unique immutable tags to Amazon ECR.
   - Packages `compose.yml`, `deploy.sh`, `validate.py`, `database-preflight.py`, and `images.json` into a release tarball and uploads it to Amazon S3.
   - Invokes AWS Systems Manager (SSM) on `i-0d7abe00772ca6669` via `deploy/aws/send-command.py` and streams status until verified healthy.

---

## 8. Phase 6: Post-Deployment Verification & Rollback

### 1. Verify Deployment on the EC2 Host

```bash
# 1. Confirm the release symlink points to the latest commit
sudo readlink -f /opt/hrms/testing/current

# 2. Check running Docker containers
sudo docker ps --filter name=hrms-testing-aws

# 3. Test local readiness and health endpoints
curl -i http://127.0.0.1:8115/health
curl -i http://127.0.0.1:8115/health/ready
curl -i http://127.0.0.1:8180/healthz

# 4. Check the frontend runtime configuration injection
curl -s http://127.0.0.1:8180/config.js
```

### 2. Verify Application Functionality in Browser

1. Open `https://testinghrms.alvision.in` in your browser.
2. Verify that the testing badge appears and the UI renders without console errors.
3. Test authentication (Sign in as tenant admin or employee).
4. Verify document upload / KYC file attachment.
5. Check that background jobs are scheduled and recording metrics at `http://127.0.0.1:8115/metrics`.

### 3. Rollback Procedure

#### Automatic Service Rollback:
If an updated image fails container health checks (`/health/ready` or `/healthz`) during `deploy.sh`, the script automatically rolls back to the previous running images without human intervention.

#### Manual Code-Only Rollback:
If you need to roll back to an earlier release without downgrading the database schema:

```bash
# 1. List available releases
ls -l /opt/hrms/testing/releases

# 2. Run deploy.sh in --code-only mode pointing to the previous release
sudo bash /opt/hrms/testing/releases/<PREVIOUS_RELEASE_DIR>/deploy.sh \
  /opt/hrms/testing/releases/<PREVIOUS_RELEASE_DIR> --code-only
```

---

## 9. Troubleshooting Guide

| Issue | Cause | Resolution |
|---|---|---|
| **Database preflight fails: `Migration owner cannot bypass forced RLS`** | The `"Hrms"` user lacks the `BYPASSRLS` attribute in PostgreSQL. | Connect to RDS as `"Hrms"` and execute: `ALTER ROLE "Hrms" WITH BYPASSRLS;`. |
| **SSM command fails with `InvocationDoesNotExist` or timeout** | EC2 instance is offline in Systems Manager or lacks SSM IAM permissions. | Verify that the `EC2InstanceProfile` is attached to EC2 and that `amazon-ssm-agent` is running (`sudo systemctl status amazon-ssm-agent`). |
| **`Deployment configuration failed: ValueError` during deploy** | One of the `/etc/hrms/testing.*.env` files contains syntax errors, unescaped quotes, or mismatched role passwords. | Run `sudo python3 /opt/hrms/testing/releases/<RELEASE>/validate.py /opt/hrms/testing/releases/<RELEASE>` locally on EC2 to see exact validation errors. |
| **API healthcheck fails (`503 Service Unavailable` on `/health/ready`)** | The database connection failed, or Alembic migrations have not run to head. | Check container logs: `sudo docker compose -f /opt/hrms/testing/current/compose.yml logs api`. |
| **Frontend displays white screen or `Network Error`** | `HRMS_WEB_API_URL` or `HRMS_CORS_ORIGINS` mismatch. | Confirm `HRMS_WEB_API_URL=https://hrmsapi.alvision.in` and `HRMS_CORS_ORIGINS=https://testinghrms.alvision.in` in `/etc/hrms/testing.runtime.env` and `/etc/hrms/testing.deploy.env`. |
