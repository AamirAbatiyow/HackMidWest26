# Vouch on Akamai Cloud (us-ord).
#
#   internet ──TLS──▶ NodeBalancer ──VPC(ingress)──▶ app Linode(s) :8101  (API + frontend contract)
#                                                        │ VPC(model)
#                                                        ▼
#                                                  model Linode :8201  (PyTorch risk model + LIME; no public interface)
#                                                        │ VPC(data)
#                                                        ▼
#                                        Managed PostgreSQL (pgvector)   Object Storage (attachments)
#
# Nothing here is applied without LINODE_TOKEN; `make tf-validate` and `make tf-plan` are safe to run.

locals {
  name       = var.prefix
  tags       = var.tags
  app_ips    = slice(var.app_vpc_ips, 0, var.app_count)
  proxy_ip   = var.app_vpc_ips[0]
  bucket     = var.bucket_label != "" ? var.bucket_label : "${var.prefix}-attachments-${random_id.bucket.hex}"
  tls_cert   = var.tls_cert_pem != "" ? var.tls_cert_pem : tls_self_signed_cert.nb[0].cert_pem
  tls_key    = var.tls_key_pem != "" ? var.tls_key_pem : tls_private_key.nb[0].private_key_pem
  public_url = var.public_domain != "" ? "https://${var.public_domain}" : "https://${linode_nodebalancer.ingress.ipv4}"
  database_url = var.enable_postgres ? format(
    "postgresql://%s:%s@%s:%d/postgres?sslmode=require",
    linode_database_postgresql_v2.main[0].root_username,
    linode_database_postgresql_v2.main[0].root_password,
    linode_database_postgresql_v2.main[0].host_primary,
    linode_database_postgresql_v2.main[0].port,
  ) : ""
}

resource "random_id" "bucket" {
  byte_length = 3
}

# --- Network: one VPC, three subnets ---------------------------------------------------------------

resource "linode_vpc" "main" {
  label       = "${local.name}-vpc"
  region      = var.region
  description = "Vouch: ingress/app, private model serving, data"
}

resource "linode_vpc_subnet" "ingress" {
  vpc_id = linode_vpc.main.id
  label  = "ingress-app"
  ipv4   = var.vpc_cidrs.ingress
}

resource "linode_vpc_subnet" "model" {
  vpc_id = linode_vpc.main.id
  label  = "model"
  ipv4   = var.vpc_cidrs.model
}

resource "linode_vpc_subnet" "data" {
  vpc_id = linode_vpc.main.id
  label  = "data"
  ipv4   = var.vpc_cidrs.data
}

# --- Cloud Firewalls (default DROP inbound) --------------------------------------------------------

# App Linodes: API only from the NodeBalancer's VPC range; SSH only from admin CIDRs; proxy only from the model subnet.
resource "linode_firewall" "app" {
  label           = "${local.name}-fw-app"
  inbound_policy  = "DROP"
  outbound_policy = "ACCEPT"
  tags            = local.tags

  inbound {
    label    = "api-from-nodebalancer"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = tostring(var.api_port)
    ipv4     = [var.nodebalancer_ipv4_range, var.vpc_cidrs.ingress]
  }

  inbound {
    label    = "egress-proxy-from-model-subnet"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = tostring(var.proxy_port)
    ipv4     = [var.vpc_cidrs.model]
  }

  dynamic "inbound" {
    for_each = length(var.admin_cidrs) > 0 ? [1] : []
    content {
      label    = "ssh-admin"
      action   = "ACCEPT"
      protocol = "TCP"
      ports    = "22"
      ipv4     = var.admin_cidrs
    }
  }

  linodes = [for i in linode_instance.app : i.id]
}

# Model Linode: no public interface at all; inference port + SSH only from the app subnet.
resource "linode_firewall" "model" {
  label           = "${local.name}-fw-model"
  inbound_policy  = "DROP"
  outbound_policy = "ACCEPT"
  tags            = local.tags

  inbound {
    label    = "inference-from-app-subnet"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = tostring(var.model_port)
    ipv4     = [var.vpc_cidrs.ingress]
  }

  inbound {
    label    = "ssh-from-app-subnet"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "22"
    ipv4     = [var.vpc_cidrs.ingress]
  }

  linodes = [linode_instance.model.id]
}

# NodeBalancer: HTTPS (and optionally HTTP) from anywhere.
resource "linode_firewall" "nodebalancer" {
  label           = "${local.name}-fw-nb"
  inbound_policy  = "DROP"
  outbound_policy = "ACCEPT"
  tags            = local.tags

  inbound {
    label    = "https"
    action   = "ACCEPT"
    protocol = "TCP"
    ports    = "443"
    ipv4     = ["0.0.0.0/0"]
    ipv6     = ["::/0"]
  }

  dynamic "inbound" {
    for_each = var.enable_http ? [1] : []
    content {
      label    = "http"
      action   = "ACCEPT"
      protocol = "TCP"
      ports    = "80"
      ipv4     = ["0.0.0.0/0"]
      ipv6     = ["::/0"]
    }
  }
}

# --- Compute ---------------------------------------------------------------------------------------

resource "linode_instance" "app" {
  count           = var.app_count
  label           = "${local.name}-app-${count.index + 1}"
  region          = var.region
  type            = var.app_type
  image           = var.image
  authorized_keys = var.ssh_public_keys
  tags            = local.tags
  private_ip      = false

  metadata {
    user_data = base64encode(templatefile("${path.module}/cloud-init-app.yaml.tftpl", {
      repo_url           = var.repo_url
      repo_ref           = var.repo_ref
      api_port           = var.api_port
      proxy_port         = var.proxy_port
      proxy_ip           = local.proxy_ip
      run_proxy          = count.index == 0
      model_subnet       = var.vpc_cidrs.model
      model_url          = "http://${var.model_vpc_ip}:${var.model_port}"
      public_url         = local.public_url
      cors_origins       = join(",", concat(var.frontend_origins, [local.public_url]))
      database_url       = local.database_url
      obj_endpoint       = "https://${linode_object_storage_bucket.attachments.s3_endpoint}"
      obj_region         = "${var.object_storage_region}-1"
      obj_bucket         = linode_object_storage_bucket.attachments.label
      obj_access_key     = linode_object_storage_key.app.access_key
      obj_secret_key     = linode_object_storage_key.app.secret_key
      akamai_base_url    = var.akamai_inference_base_url
      akamai_chat_model  = var.akamai_inference_model
      akamai_embed_model = var.akamai_embedding_model
      settlement_adapter = var.settlement_adapter
      firewall_label     = "${local.name}-fw-app"
      vpc_label          = "${local.name}-vpc"
      region             = var.region
      decider_url        = var.enable_decider ? "http://${var.decider_vpc_ip}:${var.decider_port}" : ""
    }))
  }

  interface {
    purpose = "public"
  }

  interface {
    purpose   = "vpc"
    subnet_id = linode_vpc_subnet.ingress.id
    ipv4 {
      vpc = var.app_vpc_ips[count.index]
    }
  }
}

# The model server has exactly one interface: the VPC one. No public IPv4/IPv6, no 1:1 NAT.
# Outbound package/image pulls go through the forward proxy on app Linode #1.
resource "linode_instance" "model" {
  label           = "${local.name}-model"
  region          = var.region
  type            = var.model_type
  image           = var.image
  authorized_keys = var.ssh_public_keys
  tags            = local.tags
  private_ip      = false

  metadata {
    user_data = base64encode(templatefile("${path.module}/cloud-init-model.yaml.tftpl", {
      repo_url   = var.repo_url
      repo_ref   = var.repo_ref
      model_port = var.model_port
      proxy_url  = "http://${local.proxy_ip}:${var.proxy_port}"
    }))
  }

  interface {
    purpose   = "vpc"
    primary   = true
    subnet_id = linode_vpc_subnet.model.id
    ipv4 {
      vpc = var.model_vpc_ip
    }
  }
}

# --- NodeBalancer with TLS ------------------------------------------------------------------------

resource "tls_private_key" "nb" {
  count     = var.tls_cert_pem == "" ? 1 : 0
  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "nb" {
  count           = var.tls_cert_pem == "" ? 1 : 0
  private_key_pem = tls_private_key.nb[0].private_key_pem
  subject {
    common_name  = var.public_domain != "" ? var.public_domain : "vouch.local"
    organization = "Vouch (HackMidWest 2026 demo)"
  }
  dns_names             = var.public_domain != "" ? [var.public_domain] : ["vouch.local"]
  ip_addresses          = var.public_domain == "" ? [linode_nodebalancer.ingress.ipv4] : []
  validity_period_hours = 24 * 30
  allowed_uses          = ["key_encipherment", "digital_signature", "server_auth"]
}

resource "linode_nodebalancer" "ingress" {
  label                = "${local.name}-nb"
  region               = var.region
  tags                 = local.tags
  client_conn_throttle = 20
  firewall_id          = linode_firewall.nodebalancer.id
  vpcs = [{
    subnet_id  = linode_vpc_subnet.ingress.id
    ipv4_range = var.nodebalancer_ipv4_range
  }]
}

resource "linode_nodebalancer_config" "https" {
  nodebalancer_id = linode_nodebalancer.ingress.id
  port            = 443
  protocol        = "https"
  algorithm       = "roundrobin"
  stickiness      = "none"
  check           = "http"
  check_path      = "/v1/health"
  check_interval  = 10
  check_timeout   = 5
  check_attempts  = 3
  check_passive   = true
  cipher_suite    = "recommended"
  ssl_cert        = local.tls_cert
  ssl_key         = local.tls_key
}

resource "linode_nodebalancer_config" "http" {
  count           = var.enable_http ? 1 : 0
  nodebalancer_id = linode_nodebalancer.ingress.id
  port            = 80
  protocol        = "http"
  algorithm       = "roundrobin"
  check           = "http"
  check_path      = "/v1/health"
  check_interval  = 10
  check_timeout   = 5
  check_attempts  = 3
}

resource "linode_nodebalancer_node" "https" {
  count           = var.app_count
  nodebalancer_id = linode_nodebalancer.ingress.id
  config_id       = linode_nodebalancer_config.https.id
  label           = "${local.name}-app-${count.index + 1}"
  address         = "${var.app_vpc_ips[count.index]}:${var.api_port}"
  subnet_id       = linode_vpc_subnet.ingress.id
  weight          = 100
  mode            = "accept"
  depends_on      = [linode_instance.app]
}

resource "linode_nodebalancer_node" "http" {
  count           = var.enable_http ? var.app_count : 0
  nodebalancer_id = linode_nodebalancer.ingress.id
  config_id       = linode_nodebalancer_config.http[0].id
  label           = "${local.name}-app-${count.index + 1}-http"
  address         = "${var.app_vpc_ips[count.index]}:${var.api_port}"
  subnet_id       = linode_vpc_subnet.ingress.id
  weight          = 100
  mode            = "accept"
  depends_on      = [linode_instance.app]
}

# --- Object Storage (invoice attachments, model bundles) ----------------------------------------

resource "linode_object_storage_bucket" "attachments" {
  label  = local.bucket
  region = var.object_storage_region
  acl    = "private"
}

resource "linode_object_storage_key" "app" {
  label = "${local.name}-app"
  bucket_access {
    bucket_name = linode_object_storage_bucket.attachments.label
    region      = var.object_storage_region
    permissions = "read_write"
  }
}

# --- Managed PostgreSQL (pgvector) ----------------------------------------------------------------

resource "linode_database_postgresql_v2" "main" {
  count        = var.enable_postgres ? 1 : 0
  label        = "${local.name}-pg"
  engine_id    = var.postgres_engine
  region       = var.region
  type         = var.postgres_type
  cluster_size = 1
  # Only the app subnet may connect; the model Linode and the internet cannot.
  allow_list = [var.vpc_cidrs.ingress]

  private_network = {
    vpc_id        = linode_vpc.main.id
    subnet_id     = linode_vpc_subnet.data.id
    public_access = false
  }

  timeouts {
    create = "60m"
    update = "60m"
    delete = "30m"
  }
  # pgvector: the API runs `CREATE EXTENSION IF NOT EXISTS vector` on first start (vendor embeddings).
}
