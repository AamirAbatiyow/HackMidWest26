# --- auth / naming --------------------------------------------------------------------------------

variable "linode_token" {
  description = "Akamai Cloud API token. Pass via TF_VAR_linode_token (make deploy-akamai does); never put it in tfvars."
  type        = string
  default     = ""
  sensitive   = true
}

variable "prefix" {
  description = "Label prefix for every resource."
  type        = string
  default     = "vouch"
}

variable "region" {
  description = "Akamai Cloud region for compute, VPC, NodeBalancer and the managed database."
  type        = string
  default     = "us-ord"
}

variable "tags" {
  description = "Tags applied to every taggable resource (the destroy script and billing filter on these)."
  type        = list(string)
  default     = ["vouch-hackathon"]
}

variable "image" {
  type    = string
  default = "linode/ubuntu24.04"
}

# --- network --------------------------------------------------------------------------------------

variable "vpc_cidrs" {
  description = "Subnets inside the VPC. ingress carries the NodeBalancer backends + app Linodes; model is private; data holds the database."
  type = object({
    ingress = string
    model   = string
    data    = string
  })
  default = {
    ingress = "10.0.1.0/24"
    model   = "10.0.2.0/24"
    data    = "10.0.3.0/24"
  }
}

variable "nodebalancer_ipv4_range" {
  description = "/30 inside the ingress subnet the NodeBalancer sources backend traffic from (must not overlap the app IPs)."
  type        = string
  default     = "10.0.1.252/30"
}

variable "app_vpc_ips" {
  description = "Fixed VPC addresses for the app Linodes (length >= app_count)."
  type        = list(string)
  default     = ["10.0.1.10", "10.0.1.11"]
}

variable "model_vpc_ip" {
  type    = string
  default = "10.0.2.10"
}

variable "admin_cidrs" {
  description = "CIDRs allowed to SSH to the app Linodes (your venue / home IP, e.g. [\"203.0.113.7/32\"]). Empty = no SSH from the internet."
  type        = list(string)
  default     = []
}

variable "ssh_public_keys" {
  description = "SSH public keys installed on every Linode (root). Needed by deploy_akamai.sh to push secrets."
  type        = list(string)
  default     = []
}

# --- compute --------------------------------------------------------------------------------------

variable "app_count" {
  description = "Number of app Linodes behind the NodeBalancer (1 or 2)."
  type        = number
  default     = 1
  validation {
    condition     = var.app_count >= 1 && var.app_count <= 2
    error_message = "app_count must be 1 or 2."
  }
}

variable "app_type" {
  description = "Plan for the app Linodes. g6-standard-2 = 2 vCPU / 4 GB shared (torch CPU + API fit comfortably)."
  type        = string
  default     = "g6-standard-2"
}

variable "model_type" {
  description = "Plan for the private model-serving Linode (CPU inference, no GPU)."
  type        = string
  default     = "g6-standard-2"
}

variable "api_port" {
  type    = number
  default = 8101
}

variable "model_port" {
  type    = number
  default = 8201
}

variable "proxy_port" {
  description = "HTTP forward proxy on app Linode #1 that gives the model Linode apt/Docker/git egress without a public interface."
  type        = number
  default     = 3128
}

# --- application ----------------------------------------------------------------------------------

variable "repo_url" {
  description = "Git URL cloned onto the Linodes by cloud-init."
  type        = string
  default     = "https://github.com/AamirAbatiyow/HackMidWest26.git"
}

variable "repo_ref" {
  description = "Branch or tag to check out."
  type        = string
  default     = "main"
}

variable "frontend_origins" {
  description = "Origins allowed by CORS (where the React app is served from)."
  type        = list(string)
  default     = ["http://localhost:5173"]
}

variable "public_domain" {
  description = "DNS name pointing at the NodeBalancer (used for the TLS certificate CN and VOUCH_PUBLIC_URL). Empty = use the NodeBalancer IP."
  type        = string
  default     = ""
}

variable "tls_cert_pem" {
  description = "PEM certificate chain for the NodeBalancer's HTTPS listener. Empty = a self-signed certificate is generated (browsers warn; fine for a demo)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "tls_key_pem" {
  description = "PEM private key matching tls_cert_pem."
  type        = string
  default     = ""
  sensitive   = true
}

variable "enable_http" {
  description = "Also expose plain HTTP on :80 (handy before DNS/TLS is sorted). The frontend should use https."
  type        = bool
  default     = true
}

variable "akamai_inference_base_url" {
  type    = string
  default = "https://ws.akamai-workshops.com/v1"
}

variable "akamai_inference_model" {
  type    = string
  default = "hackathon-chat"
}

variable "akamai_embedding_model" {
  type    = string
  default = "hackathon-embedding"
}

variable "settlement_adapter" {
  description = "mock (simulated receipts) or xrpl (real XRPL testnet transactions; seeds are pushed by deploy_akamai.sh, never via Terraform)."
  type        = string
  default     = "xrpl"
}

# --- data -----------------------------------------------------------------------------------------

variable "enable_postgres" {
  description = "Provision Akamai Managed PostgreSQL (takes 10-20 minutes). false = SQLite on the app Linode's disk."
  type        = bool
  default     = true
}

variable "postgres_type" {
  description = "Managed database plan (single node, smallest)."
  type        = string
  default     = "g6-nanode-1"
}

variable "postgres_engine" {
  type    = string
  default = "postgresql/16"
}

variable "object_storage_region" {
  description = "Object Storage region (endpoint https://<region>-1.linodeobjects.com)."
  type        = string
  default     = "us-ord"
}

variable "bucket_label" {
  description = "Object Storage bucket for invoice attachments and model bundles. Empty = <prefix>-attachments-<random>."
  type        = string
  default     = ""
}
