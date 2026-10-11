variable "prefix" {
  description = "Name prefix for all resources (the concept you are shipping, e.g. vouch)."
  type        = string
  default     = "hackmw"
}

variable "region" {
  description = "Akamai Cloud region for compute/VPC/DB. `linode-cli regions list`."
  type        = string
  default     = "us-ord"
}

variable "use_lke" {
  description = "false: one compute instance running docker compose (fastest). true: LKE cluster + k8s manifests."
  type        = bool
  default     = false
}

variable "instance_type" {
  description = "Compute plan for the single-instance path. g6-standard-2 = 2 vCPU / 4 GB."
  type        = string
  default     = "g6-standard-2"
}

variable "ssh_public_keys" {
  description = "SSH public keys allowed on the instance."
  type        = list(string)
  default     = []
}

variable "admin_cidrs" {
  description = "CIDRs allowed to SSH in. TODO: set to your venue/home IP, e.g. [\"203.0.113.7/32\"]."
  type        = list(string)
  default     = []
}

variable "repo_url" {
  description = "Git URL cloned onto the instance by cloud-init (leave empty to copy code manually)."
  type        = string
  default     = ""
}

variable "vpc_subnet_cidr" {
  type    = string
  default = "10.0.0.0/24"
}

variable "instance_vpc_ip" {
  type    = string
  default = "10.0.0.10"
}

variable "api_port" {
  description = "Host port of the project API on the instance (docker compose maps api -> 8100)."
  type        = number
  default     = 8100
}

variable "enable_nodebalancer" {
  type    = bool
  default = true
}

variable "lke_k8s_version" {
  description = "TODO: pick a currently supported version: `linode-cli lke versions-list`."
  type        = string
  default     = "1.33"
}

variable "lke_node_type" {
  type    = string
  default = "g6-standard-2"
}

variable "lke_node_count" {
  type    = number
  default = 2
}

variable "object_storage_region" {
  description = "Object Storage region (endpoint becomes https://<region>-1.linodeobjects.com)."
  type        = string
  default     = "us-ord"
}

variable "bucket_label" {
  description = "Globally unique within the region. TODO: change before apply."
  type        = string
  default     = "hackmw-artifacts-change-me"
}

variable "enable_postgres" {
  description = "Managed Postgres takes a while to provision; start it early or use the compose Postgres on the instance."
  type        = bool
  default     = false
}

variable "postgres_type" {
  type    = string
  default = "g6-nanode-1"
}

variable "postgres_engine" {
  type    = string
  default = "postgresql/16"
}
