{
  description = "Antragsplattform (STUPA-Workflow) — FastAPI backend, Angular frontend, MCP server, admin CLI, pytex service";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";

    # The frontend compiles @stupa-makers/ui-kit straight from its source via a
    # tsconfig path mapping into frontend/vendor/ui-kit (a git submodule). Pin
    # the same commit here so the frontend package builds without submodules.
    ui-kit = {
      url = "github:STUPA-MAKERS/ui-kit/17667747b7853eb67d3c512178e6be805f3370a0";
      flake = false;
    };
  };

  outputs = { self, nixpkgs, ui-kit }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};

      python = pkgs.python313;
      nodejs = pkgs.nodejs_22;

      # Drop into the user's interactive zsh (loads ~/.zshrc); guarded so
      # `nix develop -c <cmd>` and non-interactive uses still run in bash.
      zshExec = ''[[ $- == *i* ]] && exec ${pkgs.zsh}/bin/zsh'';

      # Shared Python dev tooling. Project dependencies themselves are installed
      # per component with uv/pip into a virtualenv (see the shellHooks) rather
      # than resolved through Nix — several backend deps (pycheval,
      # clamd, python-magic, ...) are pinned tightly and not in nixpkgs.
      pyTools = [
        python
        pkgs.uv
        pkgs.ruff
        pkgs.basedpyright
      ];

      # The Angular app is built with the @angular/build application builder;
      # output lands in dist/antragsplattform/browser.
      frontend = pkgs.buildNpmPackage {
        pname = "antragsplattform-frontend";
        version = "0.0.0";
        src = ./frontend;

        inherit nodejs;
        npmDepsHash = "sha256-0Uz+JcaKhHBdZKQ4sULfvFFFZ9lWXgScbWznZbB+G8o=";
        npmBuildScript = "build";

        env.NG_CLI_ANALYTICS = "false";
        CI = "true";

        # Provide the ui-kit sources the tsconfig path mapping expects.
        preBuild = ''
          rm -rf vendor/ui-kit
          mkdir -p vendor
          cp -r ${ui-kit} vendor/ui-kit
          chmod -R u+w vendor/ui-kit
        '';

        installPhase = ''
          runHook preInstall
          mkdir -p $out
          cp -r dist/antragsplattform/browser/. $out/
          runHook postInstall
        '';

        meta = {
          description = "Antragsplattform Angular frontend";
          homepage = "https://github.com/STUPA-MAKERS/STUPA-Workflow";
        };
      };

      # Native libraries a plain `pip install` cannot supply: libstdc++ for
      # greenlet (SQLAlchemy async) and libmagic for python-magic. Append to
      # LD_LIBRARY_PATH; a bare assignment breaks the Nix binaries in the shell.
      pyNativeLibs = [ pkgs.stdenv.cc.cc.lib pkgs.file ];
      pyLibPath = pkgs.lib.makeLibraryPath pyNativeLibs;
      pyLibHook = ''export LD_LIBRARY_PATH="${pyLibPath}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"'';

      mkPyShell = name: extraPkgs: hint:
        pkgs.mkShell {
          packages = pyTools ++ pyNativeLibs ++ extraPkgs;
          shellHook = ''
            ${pyLibHook}
            echo "STUPA-Workflow ${name} dev shell — python ${python.version}, uv, ruff, basedpyright"
            ${hint}
            ${zshExec}
          '';
        };
    in
    {
      packages.${system} = {
        default = frontend;
        frontend = frontend;
      };

      devShells.${system} = {
        # Everything at once: Node + Python toolchains for the whole monorepo.
        default = pkgs.mkShell {
          packages = pyTools ++ pyNativeLibs ++ [
            nodejs
            pkgs.postgresql # psql for the admin CLI / local DB
          ];
          shellHook = ''
            ${pyLibHook}
            echo "STUPA-Workflow dev shell — node $(node --version), python ${python.version}, uv"
            echo "Per-component shells: nix develop .#backend | .#frontend | .#mcp | .#admin-cli | .#pytex"
            ${zshExec}
          '';
        };

        frontend = pkgs.mkShell {
          packages = [ nodejs ];
          shellHook = ''
            echo "STUPA-Workflow frontend dev shell — node $(node --version)"
            echo "npm ci && npm start  (needs the ui-kit git submodule: git submodule update --init)"
            ${zshExec}
          '';
        };

        # python-magic needs libmagic (pkgs.file) at runtime.
        backend = mkPyShell "backend" [ pkgs.file pkgs.postgresql ]
          "echo 'Setup: uv venv && uv pip install -e .[dev]  (or: pip install -e .)'";

        mcp = mkPyShell "mcp" [ ]
          "echo 'Setup: uv venv && uv pip install -e .'";

        admin-cli = mkPyShell "admin-cli" [ pkgs.postgresql ]
          "echo 'Setup: uv venv && uv pip install -e .'";

        pytex = mkPyShell "pytex" [ ]
          "echo 'Setup: uv venv && uv pip install -e .[dev]  (pulls pytex-preprocessor)'";
      };
    };
}
