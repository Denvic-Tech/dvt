variable "CONTAINER_REGISTRY_URL" {
  default = "cr.distribution.denvic.tech"
}

variable "DVT_RELEASE_TAG" {
  default = ""

  validation {
    condition = length(regexall("^[0-9]+\\.[0-9]+\\.[0-9]+(-rc[0-9]+)?$", DVT_RELEASE_TAG)) == 1
    error_message = "DVT_RELEASE_TAG must be a stable or RC version such as 1.25.0 or 1.25.0-rc1."
  }
}

variable "DVT_CANDIDATE_TAG" {
  default = ""

  validation {
    condition = DVT_CANDIDATE_TAG != ""
    error_message = "DVT_CANDIDATE_TAG must not be empty."
  }
}

function "candidate_tags" {
  params = [repository]
  result = ["${CONTAINER_REGISTRY_URL}/dvt/${repository}:${DVT_CANDIDATE_TAG}"]
}

group "release" {
  targets = [
    "orchestrator",
    "task-worker",
    "project-scheduler",
    "gateway",
    "dvt-ai-mcp",
    "installation_manager",
    "ui",
    "proxy",
  ]
}

target "orchestrator" {
  tags = candidate_tags("orchestrator")
}

target "task-worker" {
  tags = candidate_tags("task-worker")
}

target "project-scheduler" {
  tags = candidate_tags("project-scheduler")
}

target "gateway" {
  tags = candidate_tags("gateway")
}

target "dvt-ai-mcp" {
  tags = candidate_tags("dvt-ai-mcp")
}

target "installation_manager" {
  tags = candidate_tags("installation_manager")
}

target "ui" {
  context = "services/ui"
  dockerfile = "Dockerfile"
  args = {
    VITE_API_BASE_URL = "/api"
  }
  tags = candidate_tags("ui")
}

target "proxy" {
  tags = candidate_tags("proxy")
}
