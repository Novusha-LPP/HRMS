# Frontend CI/CD on ECS Fargate

The release pipeline builds the React/Nginx image once. After a successful release, it
automatically deploys that image to testing when the repository variable
`FRONTEND_ECS_ENABLED` is `true`. Production is promoted manually using the digest from a
successful testing deployment.

```text
PR → checks → merge release PR → publish GHCR web@sha256:…
                                      │
                                      └→ copy to ECR → testing ECS service
                                                           │ verify
                                                           └→ manual production promotion
```

The workflow copies the released image from GHCR to ECR without rebuilding it, registers
a new revision of the service's current task definition with the selected container image
changed, and waits for the ECS deployment. Environment settings stay in each service's
task definition. Both environments therefore run the same image digest.

The workflow updates an **existing frontend service**. Create its AWS infrastructure
first. Backend deployment, database migrations, scheduled jobs, and infrastructure
provisioning are separate operations. The frontend and API share a product version; check
API compatibility before deploying a newer frontend independently.

## AWS prerequisites

Provision testing and production separately, with an ECR repository, ECS cluster, Fargate
task definition, and running frontend service in each environment. Each service needs:

- Linux/X86_64 Fargate tasks with `awsvpc` networking and a container named `web` (or the
  value of `ECS_CONTAINER_NAME`), listening on TCP **8080**.
- An Application Load Balancer target group with target type **IP**, traffic port 8080,
  health check path **`/healthz`**, and HTTPS on the public listener. Allow task ingress
  from the load balancer's security group.
- The rolling deployment controller (`ECS`) with deployment circuit breaker and rollback
  enabled. Start with a healthy, completed deployment so ECS has a rollback target.
- An execution role that can pull the ECR image and write container logs to a precreated
  CloudWatch log group. Set up an application task role only if the task needs AWS access.
- Network access to ECR, its image layer storage, and CloudWatch Logs, through appropriate
  VPC endpoints or outbound connectivity.
- Runtime environment variables configured in its task definition:

| Variable | Testing example | Purpose |
|---|---|---|
| `HRMS_WEB_API_URL` | `https://hrmsapi.example.com` | Absolute API base URL, without `/v1` or a trailing slash; client requests already include `/v1` |
| `HRMS_ENVIRONMENT` | `testing` | `testing` or `production`; controls the visible testing badge and error reporting environment |
| `HRMS_WEB_SENTRY_DSN` | Optional Sentry DSN | Browser error reporting |

These values are public browser configuration. Database passwords, AWS credentials, and
other secrets do not belong in frontend settings. The image generates `/config.js` and
Nginx security headers at startup and needs a writable `/tmp`. See
[`deploy/web/40-hrms-config.sh`](../deploy/web/40-hrms-config.sh).

Configure a container health check in the ECS task definition; ECS does not infer it from
the image's Docker `HEALTHCHECK`:

```json
{
  "command": ["CMD-SHELL", "wget -qO- http://127.0.0.1:8080/healthz >/dev/null || exit 1"],
  "interval": 30,
  "timeout": 5,
  "retries": 3,
  "startPeriod": 10
}
```

Configure the API's CORS origins to allow the frontend HTTPS domain, including when both
use the same origin: cookie-write requests explicitly validate the Origin header. A shared
load balancer can route `/v1/*` to the API and other paths to the web
service; in that arrangement use the site's absolute origin for `HRMS_WEB_API_URL` and
account separately for any API health or documentation routes.

AWS documents the [ECS health check configuration](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/healthcheck.html)
and [deployment circuit breaker](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html).

## GitHub configuration

Create GitHub environments named **`frontend-testing`** and **`frontend-production`**.
Restrict both environments' deployment branches to `main`. Production may additionally
use required reviewers if the repository's GitHub plan supports them. Only a manual run
targeting production deploys there.

Set these **environment variables** in each GitHub environment:

| Variable | Example |
|---|---|
| `AWS_REGION` | `ap-south-1` |
| `AWS_ROLE_ARN` | `arn:aws:iam::123456789012:role/github-hrms-frontend-testing` |
| `ECR_REPOSITORY` | `hrms-web-testing` (repository name, not a registry URL) |
| `ECS_CLUSTER` | `hrms-testing` |
| `ECS_SERVICE` | `hrms-web-testing` |
| `ECS_CONTAINER_NAME` | `web` (default if omitted) |

The repository variable **`FRONTEND_ECS_ENABLED=true`** enables automatic testing
deployment after successful release publication. Leave it unset until AWS and both GitHub
environments are configured. This switch only controls automatic release deployment;
manual workflow runs use the selected environment's configuration.

The deployment uses the job's `GITHUB_TOKEN` to read the repository's GHCR web package.
Ensure that the package grants Actions access to this repository, especially if it was
originally published elsewhere. AWS access uses short-lived OIDC credentials.

## AWS OIDC role

Add the IAM OIDC provider `https://token.actions.githubusercontent.com` with audience
`sts.amazonaws.com`. Create a separate deployment role for each environment. A testing
role trust policy looks like this; replace the account and repository identity:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:Novusha-LPP/HRMS:environment:frontend-testing"
        }
      }
    }
  ]
}
```

Use `frontend-production` in the production role's subject. Match the repository's case
and actual subject format: newer repositories or those that opted into immutable
subjects include owner and repository IDs. An environment subject does not contain the
branch, which is why the GitHub environment must restrict deployments to `main`.
See [GitHub's AWS OIDC setup](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).

Attach a policy scoped to that environment's repository, service, and exact task roles.
This example uses the testing resource names above:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EcrLogin",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "CopyAndVerifyFrontendImage",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
        "ecr:DescribeImages",
        "ecr:DescribeRepositories",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": "arn:aws:ecr:ap-south-1:123456789012:repository/hrms-web-testing"
    },
    {
      "Sid": "DeployFrontendService",
      "Effect": "Allow",
      "Action": ["ecs:DescribeServices", "ecs:UpdateService"],
      "Resource": "arn:aws:ecs:ap-south-1:123456789012:service/hrms-testing/hrms-web-testing"
    },
    {
      "Sid": "ReadFrontendTaskDefinition",
      "Effect": "Allow",
      "Action": "ecs:DescribeTaskDefinition",
      "Resource": "*"
    },
    {
      "Sid": "RegisterTaskRevision",
      "Effect": "Allow",
      "Action": "ecs:RegisterTaskDefinition",
      "Resource": "*"
    },
    {
      "Sid": "PassOnlyFrontendTaskRoles",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": [
        "arn:aws:iam::123456789012:role/hrms-web-testing-execution",
        "arn:aws:iam::123456789012:role/hrms-web-testing-task"
      ],
      "Condition": {
        "StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}
      }
    }
  ]
}
```

`DescribeTaskDefinition` requires `Resource: "*"` because it does not support resource-level
permissions. The service update and role passing remain scoped to the frontend resources.
Remove the task role ARN if the task definition does not use one, and use the production
resources in the production role. These are deployment permissions; the task execution
role and application task role have their own runtime permissions. The workflow does not
need permission to create clusters, services, repositories, IAM roles, or load balancers.
See the [ECS IAM action reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ecs.html).

## Release, promotion, and rollback

1. Merge the release PR after CI passes. The release workflow publishes the versioned
   frontend image to GHCR. With `FRONTEND_ECS_ENABLED=true`, it calls
   [`deploy-frontend-ecs.yml`](../.github/workflows/deploy-frontend-ecs.yml) for testing.
2. Confirm the testing deployment job succeeded. Open the testing site, verify login and
   the changed screens against the deployed API, and check browser errors and CloudWatch
   logs. The load balancer health check proves Nginx is serving; it does not prove API
   compatibility or user workflows.
3. Copy the complete source image digest from the successful testing job's summary
   (`sha256:` followed by 64 hexadecimal characters).
4. In **Actions → Deploy frontend to ECS → Run workflow**, select branch `main`, choose
   `environment=production`, and paste that digest into `image_digest`. Complete any
   configured GitHub environment review. The workflow copies the same image into the
   production ECR repository and deploys it without a rebuild.
5. Verify the production site and the deployment summary. Keep the source digest and
   task definition revision with the release record.

For rollback, manually run the same workflow for the affected environment with the digest
from its previous successful deployment. Retain those GHCR and ECR images in registry
cleanup policies. ECS circuit breaker rollback covers startup and health failures; use
manual rollback for application regressions detected after the deployment completes.
The operator must choose a successfully tested digest before promoting to production;
the manual input itself is not evidence of testing.

The workflow reads the service's current task definition before each deployment. Configure
runtime settings and networking through your infrastructure management process; deployment
preserves the current task definition's settings and replaces only the named web image.
Do not put the API or scheduled jobs in this frontend service task definition, because
updating a service replaces its tasks.
