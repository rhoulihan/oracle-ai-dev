# When the MCP server will not start

Both failures below are environment-shaped: the server is spawned as a child of
the agent, so it does not inherit the shell you configured, and an optional
setting that resolves to an empty string is not the same as one left unset.

## The child process cannot find Java

On macOS with a Homebrew-installed OpenJDK (keg-only, not linked to /usr/bin),
the oracle-ai-dev sqlcl MCP server process — spawned as a child of Claude Code
— does not inherit the interactive shell's JAVA_HOME and sees only the macOS
/usr/bin/java stub. This makes the MCP server fail at launch with 'could not
read the Java version from /usr/bin/java; Oracle SQLcl requires Java 17+',
even though `java -version` works fine in a normal terminal. Root cause was
confirmed by reproducing the failure with a clean environment (`env -i
HOME=... PATH=/usr/bin:/bin:/usr/sbin:/sbin bash sqlcl-mcp.sh`). Verified fix:
symlink the Homebrew JDK into the standard macOS JVM discovery location —
`sudo ln -sfn $(brew --prefix openjdk)/libexec/openjdk.jdk
/Library/Java/JavaVirtualMachines/openjdk.jdk` — then restart Claude Code; no
OS/laptop restart needed.

## An optional TNS_ADMIN arrives as an empty string

The oracle-ai-dev plugin's .mcp.json unconditionally interpolates TNS_ADMIN
from ${user_config.tns_admin}; when that optional config is unset it emits
TNS_ADMIN="" (empty string) instead of omitting the var. SQLcl treats empty
TNS_ADMIN differently from unset: empty triggers a NullPointerException in
oracle.dbtools.raptor.utils.TNSHelper.getTnsnamesDir, surfacing as ORA-17869
on connect, while a fully unset TNS_ADMIN connects fine. Setting
pluginConfigs.oracle-ai-dev@oracle-ai-dev-marketplace.tns_admin in
~/.claude/settings.json does NOT fix this — confirmed empirically: the value
was set correctly in settings.json and Claude Code was restarted, but MCP
connect still failed with ORA-17869. The verified working fix is to edit the
cached plugin's .mcp.json directly
(~/.claude/plugins/cache/oracle-ai-dev-marketplace/oracle-ai-dev/<version>/.mcp.json),
hardcoding TNS_ADMIN to a real directory containing a tnsnames.ora file (an
empty placeholder file suffices), then restart Claude Code. This patch is lost
on plugin update.

## Sources

- Field-verified while wiring the plugin's own MCP server, 2026-09.
