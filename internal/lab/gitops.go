package lab

import (
	"bufio"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/pem"
	"errors"
	"fmt"
	"net"
	"os"
	"regexp"
	"strings"
	"time"

	"golang.org/x/crypto/ssh"
	"golang.org/x/crypto/ssh/knownhosts"
)

// GitOpsOptions configures deploy-gitops.
type GitOpsOptions struct {
	// RepoURL overrides the url in config/gitops/git-repository.yaml.
	RepoURL string
	// NoPrompt skips waiting for the deploy key to be added.
	NoPrompt bool
}

// DeployGitOps installs Flux and points it at the Git repository, which
// then deploys infrastructure/ and apps/.
func (l *Lab) DeployGitOps(ctx context.Context, opts GitOpsOptions) error {
	l.Log.Section("🚀 GitOps Deployment")

	if err := l.checkBootstrap(ctx); err != nil {
		return err
	}
	gitRepository, err := l.gitRepositoryManifest(opts.RepoURL)
	if err != nil {
		return err
	}
	repoURL := gitRepositoryURL(gitRepository)

	if err := l.installFluxControllers(ctx); err != nil {
		return err
	}
	publicKey, err := l.generateDeployKey()
	if err != nil {
		return err
	}
	if err := l.createFluxSecret(ctx, sshHost(repoURL)); err != nil {
		return err
	}
	l.showDeployKey(repoURL, publicKey, opts.NoPrompt)

	l.Log.Step("Creating Git source...")
	if err := l.applyManifest(ctx, gitRepository); err != nil {
		return fmt.Errorf("creating GitRepository: %w", err)
	}
	l.Log.Step("Waiting for GitRepository to sync...")
	if err := l.kubectl(ctx, "wait", "--for=condition=ready", "gitrepository", "dev-lab-repo",
		"-n", "flux-system", "--timeout=120s"); err != nil {
		l.Log.Warn("⚠️  GitRepository may not be ready yet (is the deploy key added?). Continuing...")
	} else {
		l.Log.OK("GitRepository synced successfully")
	}

	l.Log.Step("Applying Git-managed kustomizations...")
	if err := l.applyFile(ctx, l.Home.Path("clusters", "dev-lab", "dev-lab-kustomizations.yaml")); err != nil {
		return fmt.Errorf("applying kustomizations: %w", err)
	}
	l.Log.OK("Git-managed kustomizations applied")

	l.waitForGitOps(ctx)
	l.showGitOpsInfo()
	return nil
}

func (l *Lab) installFluxControllers(ctx context.Context) error {
	l.Log.Step("Installing Flux controllers...")
	if _, err := l.kubectlOutput(ctx, "get", "deployment", "-n", "flux-system", "source-controller"); err == nil {
		l.Log.OK("Flux controllers already installed")
		return nil
	}
	if err := l.Run.Run(ctx, l.ToolCmd("flux", "install", "--context", Context)); err != nil {
		return fmt.Errorf("installing Flux controllers: %w", err)
	}
	if err := l.kubectl(ctx, "wait", "--for=condition=available", "deployment", "--all",
		"-n", "flux-system", "--timeout=300s"); err != nil {
		return fmt.Errorf("waiting for Flux controllers: %w", err)
	}
	l.Log.OK("Flux controllers installed and ready")
	return nil
}

// deployKeyPath is the SSH key Flux uses to read the repository. A new key
// is generated on every deploy-gitops run, as before.
func (l *Lab) deployKeyPath() string {
	return l.Home.Path("flux-deploy-key")
}

// generateDeployKey writes a new ed25519 key pair and returns the public
// key in authorized_keys format.
func (l *Lab) generateDeployKey() (string, error) {
	l.Log.Step("Generating SSH deploy key...")
	comment := "flux-dev-lab-" + time.Now().Format("20060102")
	private, public, err := NewDeployKey(comment)
	if err != nil {
		return "", err
	}
	if err := os.WriteFile(l.deployKeyPath(), private, 0o600); err != nil {
		return "", err
	}
	if err := os.WriteFile(l.deployKeyPath()+".pub", []byte(public), 0o644); err != nil {
		return "", err
	}
	l.Log.OK("SSH key pair generated: %s", l.deployKeyPath())
	return strings.TrimSpace(public), nil
}

// NewDeployKey returns an OpenSSH private key (PEM) and its public key line.
func NewDeployKey(comment string) ([]byte, string, error) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return nil, "", err
	}
	block, err := ssh.MarshalPrivateKey(privateKey, comment)
	if err != nil {
		return nil, "", err
	}
	sshPublic, err := ssh.NewPublicKey(publicKey)
	if err != nil {
		return nil, "", err
	}
	public := strings.TrimSpace(string(ssh.MarshalAuthorizedKey(sshPublic))) + " " + comment + "\n"
	return pem.EncodeToMemory(block), public, nil
}

func (l *Lab) createFluxSecret(ctx context.Context, host string) error {
	l.Log.Step("Creating flux-system-auth secret with the deploy key...")
	knownHosts, err := l.HostKeys(ctx, host)
	if err != nil {
		return fmt.Errorf("getting %s host keys: %w", host, err)
	}
	private, err := os.ReadFile(l.deployKeyPath())
	if err != nil {
		return err
	}
	public, err := os.ReadFile(l.deployKeyPath() + ".pub")
	if err != nil {
		return err
	}
	if err := l.applyManifest(ctx, fluxSecretManifest(private, public, strings.Join(knownHosts, "\n")+"\n")); err != nil {
		return fmt.Errorf("creating flux-system-auth secret: %w", err)
	}
	l.Log.OK("flux-system-auth secret created")
	return nil
}

func fluxSecretManifest(private, public []byte, knownHosts string) string {
	encode := func(data []byte) string { return base64.StdEncoding.EncodeToString(data) }
	return fmt.Sprintf(`apiVersion: v1
kind: Secret
metadata:
  name: flux-system-auth
  namespace: flux-system
  labels:
    app.kubernetes.io/part-of: flux
type: Opaque
data:
  identity: %s
  identity.pub: %s
  known_hosts: %s
`, encode(private), encode(public), encode([]byte(knownHosts)))
}

// errHostKey stops the SSH handshake once the host key is recorded.
var errHostKey = errors.New("host key recorded")

// ScanHostKeys returns known_hosts lines for host:22, like ssh-keyscan.
func ScanHostKeys(ctx context.Context, host string) ([]string, error) {
	var lines []string
	for _, algorithm := range []string{ssh.KeyAlgoED25519, ssh.KeyAlgoECDSA256, ssh.KeyAlgoRSASHA512} {
		config := &ssh.ClientConfig{
			User:              "git",
			HostKeyAlgorithms: []string{algorithm},
			Timeout:           10 * time.Second,
			HostKeyCallback: func(_ string, _ net.Addr, key ssh.PublicKey) error {
				lines = append(lines, knownhosts.Line([]string{host}, key))
				return errHostKey
			},
		}
		dialer := net.Dialer{Timeout: 10 * time.Second}
		conn, err := dialer.DialContext(ctx, "tcp", net.JoinHostPort(host, "22"))
		if err != nil {
			return nil, err
		}
		_, _, _, err = ssh.NewClientConn(conn, net.JoinHostPort(host, "22"), config)
		conn.Close()
		if err != nil && !errors.Is(err, errHostKey) && !strings.Contains(err.Error(), errHostKey.Error()) {
			continue // host does not offer this key type
		}
	}
	if len(lines) == 0 {
		return nil, fmt.Errorf("no host keys from %s", host)
	}
	return lines, nil
}

var repoURLLine = regexp.MustCompile(`(?m)^(\s*url:\s*)(\S+)\s*$`)

// gitRepositoryManifest reads config/gitops/git-repository.yaml, replacing
// its url when repoURL is set.
func (l *Lab) gitRepositoryManifest(repoURL string) (string, error) {
	data, err := os.ReadFile(l.Home.Path("config", "gitops", "git-repository.yaml"))
	if err != nil {
		return "", err
	}
	manifest := string(data)
	if repoURL != "" {
		if !repoURLLine.MatchString(manifest) {
			return "", fmt.Errorf("config/gitops/git-repository.yaml has no url: line")
		}
		manifest = repoURLLine.ReplaceAllString(manifest, "${1}"+repoURL)
	}
	return manifest, nil
}

func gitRepositoryURL(manifest string) string {
	if match := repoURLLine.FindStringSubmatch(manifest); match != nil {
		return match[2]
	}
	return ""
}

// sshHost returns the host of ssh://git@host/path or git@host:path.
func sshHost(repoURL string) string {
	host := strings.TrimPrefix(repoURL, "ssh://")
	if at := strings.Index(host, "@"); at >= 0 {
		host = host[at+1:]
	}
	if end := strings.IndexAny(host, ":/"); end >= 0 {
		host = host[:end]
	}
	return host
}

// repoWebURL turns ssh://git@github.com/owner/repo.git into
// https://github.com/owner/repo for the deploy key instructions.
func repoWebURL(repoURL string) string {
	path := strings.TrimPrefix(repoURL, "ssh://")
	if at := strings.Index(path, "@"); at >= 0 {
		path = path[at+1:]
	}
	path = strings.Replace(path, ":", "/", 1)
	return "https://" + strings.TrimSuffix(path, ".git")
}

func (l *Lab) showDeployKey(repoURL, publicKey string, noPrompt bool) {
	l.Log.Section("📋 Deploy Key Setup")
	l.Log.Info("Add this public key as a read-only deploy key to the repository:")
	l.Log.Plain("Repository: %s", repoWebURL(repoURL))
	l.Log.Plain("Settings → Deploy keys → Add deploy key\n")
	l.Log.Plain("%s\n%s\n%s", strings.Repeat("─", 50), publicKey, strings.Repeat("─", 50))
	l.Log.Warn("Leave 'Allow write access' unchecked.")
	if noPrompt || !l.Interactive {
		return
	}
	fmt.Fprint(l.Log.Out, "\nPress Enter when you've added the deploy key...")
	_, _ = bufio.NewReader(l.In).ReadString('\n')
}

// waitForGitOps polls the two Flux kustomizations for up to 15 minutes.
func (l *Lab) waitForGitOps(ctx context.Context) {
	l.Log.Section("🕐 Waiting for GitOps Deployment")
	l.Log.Info("Flux deploys NGINX ingress, the monitoring stack, the registry and the apps; this takes several minutes.")
	const timeout, interval = 15 * time.Minute, 10 * time.Second
	for elapsed := time.Duration(0); elapsed < timeout; elapsed += interval {
		infrastructure := l.kustomizationReady(ctx, "dev-lab-infrastructure")
		apps := l.kustomizationReady(ctx, "dev-lab-apps")
		l.Log.Step("Infrastructure: %s, Apps: %s (%s elapsed)", infrastructure, apps, elapsed)
		if infrastructure == "True" && apps == "True" {
			l.Log.OK("GitOps deployment completed successfully!")
			return
		}
		l.Sleep(interval)
	}
	l.Log.Warn("⚠️  GitOps deployment still in progress. Check: bin/devlab flux get kustomizations")
}

func (l *Lab) kustomizationReady(ctx context.Context, name string) string {
	status, err := l.kubectlOutput(ctx, "get", "kustomization", name, "-n", "flux-system",
		"-o", "jsonpath={.status.conditions[?(@.type=='Ready')].status}")
	if err != nil || strings.TrimSpace(status) == "" {
		return "Unknown"
	}
	return strings.TrimSpace(status)
}

func (l *Lab) showGitOpsInfo() {
	l.Log.Section("GitOps Status")
	l.Log.Plain("  bin/devlab flux get sources git      # Git sources")
	l.Log.Plain("  bin/devlab flux get kustomizations   # Deployments from Git")
	l.Log.Plain("  bin/devlab flux get helmreleases -A  # Helm releases")
	l.Log.Plain("\n• Infrastructure and apps are deployed from Git")
	l.Log.Plain("• Changes pushed to the repository are reconciled automatically")
}
