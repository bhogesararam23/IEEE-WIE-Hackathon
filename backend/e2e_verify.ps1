# End-to-end verification of signup / login / profile / consent / soft-delete
# against the docker-compose Postgres, driven entirely by curl.exe.
$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8011"
$email = "e2e-$([guid]::NewGuid().ToString('N').Substring(0,10))@example.com"
$pass = "Str0ngPassw0rd!"

$script:pass_count = 0
$script:fail_count = 0

function Invoke-Curl {
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [string]$Body,
        [string]$Token
    )
    $out = [System.IO.Path]::GetTempFileName()
    $args = @("-sS", "-X", $Method, "$base$Path", "-o", $out, "-w", "%{http_code}")
    if ($Body) {
        # The JSON goes through a file, not -d "<string>". PowerShell 5.1 strips
        # embedded double quotes when handing arguments to a native exe, so an
        # inline -d '{"a":"b"}' reaches curl as {a:b} and the server correctly
        # answers 422 "JSON decode error". --data-binary @file sidesteps it.
        $bodyFile = [System.IO.Path]::GetTempFileName()
        [System.IO.File]::WriteAllText($bodyFile, $Body)
        $args += @("-H", "Content-Type: application/json", "--data-binary", "@$bodyFile")
        $script:bodyFile = $bodyFile
    }
    if ($Token) { $args += @("-H", "Authorization: Bearer $Token") }
    $code = & curl.exe @args
    $raw = Get-Content $out -Raw
    Remove-Item $out -Force
    if ($script:bodyFile) { Remove-Item $script:bodyFile -Force; $script:bodyFile = $null }
    $json = $null
    # /docs and /openapi.json bodies are not JSON; a parse failure here is
    # expected, not an error, so fall back to keeping the raw text.
    if ($raw) { try { $json = $raw | ConvertFrom-Json } catch { $json = $null } }
    [pscustomobject]@{ Code = $code; Body = $json; Raw = $raw }
}

function Require-Token {
    param($Result, [string]$Step)
    if (-not $Result.Body -or -not $Result.Body.access_token) {
        Write-Output "       ABORT: $Step did not return a token (HTTP $($Result.Code))"
        Write-Output "       RAW: $($Result.Raw)"
        exit 1
    }
    $Result.Body.access_token
}

function Check {
    param([string]$Label, [int]$Actual, [int]$Expected, [string]$Note = "")
    $ok = $Actual -eq $Expected
    if ($ok) { $script:pass_count++ } else { $script:fail_count++ }
    $mark = if ($ok) { "PASS" } else { "FAIL" }
    $line = "[$mark] $Label -> $Actual"
    if ($note)     { $line += "  ($note)" }
    if (-not $ok)  { $line += "  EXPECTED $Expected" }
    Write-Output $line
}

Write-Output "===================================================================="
Write-Output " HerMediSafe auth e2e   (curl.exe  ->  uvicorn  ->  compose pg)"
Write-Output "===================================================================="
Write-Output "target user: $email"
Write-Output ""

# --- 1. signup -------------------------------------------------------------
Write-Output "-- 1. SIGNUP --------------------------------------------------------"
$r = Invoke-Curl -Method POST -Path "/auth/signup" -Body (@{email=$email; password=$pass; full_name="Asha Rao"} | ConvertTo-Json -Compress)
Check "POST /auth/signup" $r.Code 201 "new account"
$token = Require-Token $r "signup"
Write-Output "       token:  $($token.Substring(0,32))...  ($($token.Length) chars)"
Write-Output "       expiry: $($r.Body.expires_in)s = $([math]::Round($r.Body.expires_in/3600,1))h   user_id: $($r.Body.user_id)"
Write-Output "       type:   $($r.Body.token_type)"
$userId = $r.Body.user_id

# --- 2. duplicate signup ---------------------------------------------------
Write-Output ""
Write-Output "-- 2. DUPLICATE EMAIL -> 409 ---------------------------------------"
$r = Invoke-Curl -Method POST -Path "/auth/signup" -Body (@{email=$email; password="Other123!"; full_name="Impostor"} | ConvertTo-Json -Compress)
Check "POST /auth/signup (duplicate)" $r.Code 409 $r.Body.detail

# --- 3. validation ---------------------------------------------------------
Write-Output ""
Write-Output "-- 3. VALIDATION ----------------------------------------------------"
$r = Invoke-Curl -Method POST -Path "/auth/signup" -Body (@{email="not-an-email"; password=$pass; full_name="A"} | ConvertTo-Json -Compress)
Check "POST /auth/signup (bad email)" $r.Code 422 "EmailStr"
$r = Invoke-Curl -Method POST -Path "/auth/signup" -Body (@{email="x-$([guid]::NewGuid().ToString('N').Substring(0,8))@example.com"; password="short"; full_name="A"} | ConvertTo-Json -Compress)
Check "POST /auth/signup (short pw)" $r.Code 422 "min_length=8"
$r = Invoke-Curl -Method POST -Path "/auth/signup" -Body (@{email="x-$([guid]::NewGuid().ToString('N').Substring(0,8))@example.com"; password=("x"*73); full_name="A"} | ConvertTo-Json -Compress)
Check "POST /auth/signup (73-char pw)" $r.Code 422 "bcrypt 72-byte limit"

# --- 4. login --------------------------------------------------------------
Write-Output ""
Write-Output "-- 4. LOGIN ---------------------------------------------------------"
$r = Invoke-Curl -Method POST -Path "/auth/login" -Body (@{email=$email; password=$pass} | ConvertTo-Json -Compress)
Check "POST /auth/login (correct)" $r.Code 200 "token minted"
$token = Require-Token $r "login"
Write-Output "       new token: $($token.Substring(0,32))..."

$r = Invoke-Curl -Method POST -Path "/auth/login" -Body (@{email=$email; password="Wr0ngPassword!"} | ConvertTo-Json -Compress)
Check "POST /auth/login (wrong pw)" $r.Code 401 $r.Body.detail
$wrongPwBody = $r.Body.detail

$r = Invoke-Curl -Method POST -Path "/auth/login" -Body (@{email="nobody@no-such-domain-8f3a2b1c.com"; password="Wr0ngPassword!"} | ConvertTo-Json -Compress)
Check "POST /auth/login (unknown email)" $r.Code 401 $r.Body.detail
if ($r.Body.detail -eq $wrongPwBody) { Write-Output "       [PASS] 401 bodies identical -> no account enumeration" }
else { Write-Output "       [FAIL] 401 bodies differ, enumeration vector!" ; $script:fail_count++ }

# --- 5. auth guard ---------------------------------------------------------
Write-Output ""
Write-Output "-- 5. BEARER AUTH GUARD -------------------------------------------"
$r = Invoke-Curl -Method GET -Path "/users/me"
Check "GET /users/me (no header)" $r.Code 401 $r.Body.detail
$r = Invoke-Curl -Method GET -Path "/users/me" -Token "not-a-jwt"
Check "GET /users/me (garbage token)" $r.Code 401 $r.Body.detail
# RFC 6750 requires the challenge header on a 401. It must be checked on an
# *unauthenticated* request: a valid token gets a 200 and no challenge at all.
$hdr = & curl.exe -sS -D - -o NUL "$base/users/me" | Select-String "www-authenticate"
if ($hdr -match "Bearer") { Write-Output "       [PASS] 401 carries WWW-Authenticate: Bearer" } else { Write-Output "       [FAIL] no WWW-Authenticate header on 401" ; $script:fail_count++ }
$hdr200 = & curl.exe -sS -D - -o NUL "$base/users/me" -H "Authorization: Bearer $token" | Select-String "www-authenticate"
if (-not $hdr200) { Write-Output "       [PASS] 200 omits the challenge header" } else { Write-Output "       [FAIL] 200 wrongly advertises a challenge" ; $script:fail_count++ }
$r = Invoke-Curl -Method GET -Path "/users/me" -Token $token
Check "GET /users/me (valid token)" $r.Code 200 "profile is null before upsert"
Write-Output "       email: $($r.Body.email)  profile: $($r.Body.profile)  consent: $($r.Body.consent_given_at)"

# --- 6. profile ------------------------------------------------------------
Write-Output ""
Write-Output "-- 6. PROFILE UPSERT ------------------------------------------------"
$r = Invoke-Curl -Method POST -Path "/users/me/profile" -Token $token -Body (@{context_type="pregnant"; trimester=2} | ConvertTo-Json -Compress)
Check "POST /users/me/profile (create)" $r.Code 201 "201 on create"
$profileId = $r.Body.id
Write-Output "       profile id: $profileId  context: $($r.Body.context_type)  trimester: $($r.Body.trimester)"

$r = Invoke-Curl -Method POST -Path "/users/me/profile" -Token $token -Body (@{context_type="pregnant"; trimester=3} | ConvertTo-Json -Compress)
Check "POST /users/me/profile (update)" $r.Code 200 "200 on update"
if ($r.Body.id -eq $profileId) { Write-Output "       [PASS] same row reused (id $profileId), not a duplicate" } else { Write-Output "       [FAIL] new row created!" ; $script:fail_count++ }
Write-Output "       trimester now: $($r.Body.trimester)"

$r = Invoke-Curl -Method POST -Path "/users/me/profile" -Token $token -Body (@{context_type="pregnant"} | ConvertTo-Json -Compress)
Check "POST /users/me/profile (pregnant, no trimester)" $r.Code 422 "cross-field rule"
$r = Invoke-Curl -Method POST -Path "/users/me/profile" -Token $token -Body (@{context_type="general"; trimester=2} | ConvertTo-Json -Compress)
Check "POST /users/me/profile (general + trimester)" $r.Code 422 "cross-field rule"
$r = Invoke-Curl -Method POST -Path "/users/me/profile" -Body (@{context_type="general"} | ConvertTo-Json -Compress)
Check "POST /users/me/profile (no token)" $r.Code 401 $r.Body.detail

# --- 7. consent ------------------------------------------------------------
Write-Output ""
Write-Output "-- 7. CONSENT -------------------------------------------------------"
$r = Invoke-Curl -Method POST -Path "/users/me/consent" -Token $token
Check "POST /users/me/consent (first)" $r.Code 200 "already_recorded=$($r.Body.already_recorded)"
$consentAt = $r.Body.consent_given_at
Write-Output "       consent_given_at: $consentAt"
$r = Invoke-Curl -Method POST -Path "/users/me/consent" -Token $token
Check "POST /users/me/consent (repeat)" $r.Code 200 "already_recorded=$($r.Body.already_recorded)"
if ($r.Body.consent_given_at -eq $consentAt) { Write-Output "       [PASS] original timestamp preserved (not overwritten)" } else { Write-Output "       [FAIL] consent timestamp was rewritten!" ; $script:fail_count++ }
$r = Invoke-Curl -Method POST -Path "/users/me/consent"
Check "POST /users/me/consent (no token)" $r.Code 401 $r.Body.detail

# --- 8. soft delete --------------------------------------------------------
Write-Output ""
Write-Output "-- 8. SOFT DELETE ---------------------------------------------------"
$r = Invoke-Curl -Method GET -Path "/users/me" -Token $token
Check "GET /users/me (before delete)" $r.Code 200
Write-Output "       profile: $($r.Body.profile.context_type) t=$($r.Body.profile.trimester)  consent: $($r.Body.consent_given_at)"

$r = Invoke-Curl -Method DELETE -Path "/users/me" -Token $token
Check "DELETE /users/me" $r.Code 200 "soft, not hard"
$deletedAt = $r.Body.deleted_at
Write-Output "       deleted_at: $deletedAt   hard_deleted: $($r.Body.hard_deleted)"

$r = Invoke-Curl -Method GET -Path "/users/me" -Token $token
Check "GET /users/me (same still-valid token)" $r.Code 401 "token revoked by tombstone"
$r = Invoke-Curl -Method POST -Path "/auth/login" -Body (@{email=$email; password=$pass} | ConvertTo-Json -Compress)
Check "POST /auth/login (after delete)" $r.Code 401 $r.Body.detail
$r = Invoke-Curl -Method POST -Path "/users/me/profile" -Token $token -Body (@{context_type="general"} | ConvertTo-Json -Compress)
Check "POST /users/me/profile (after delete)" $r.Code 401 "cannot write after erasure"

# --- 9. docs ---------------------------------------------------------------
Write-Output ""
Write-Output "-- 9. OPENAPI / DOCS ------------------------------------------------"
$r = Invoke-Curl -Method GET -Path "/docs"
Check "GET /docs" $r.Code 200 "Swagger UI"
$spec = & curl.exe -sS "$base/openapi.json" | ConvertFrom-Json
$paths = $spec.paths.PSObject.Properties | ForEach-Object { $_.Name }
Check "openapi.json path count" $paths.Count 6 "auth x2 + users/me x4 + health"
Write-Output "       paths: $($paths -join '  ')"
$sec = $spec.components.securitySchemes.PSObject.Properties.Name
if ($sec) { Write-Output "       [PASS] securityScheme declared: $($sec -join ', ')" } else { Write-Output "       [FAIL] no bearer securityScheme in OpenAPI" ; $script:fail_count++ }
$meOp = $spec.paths.'/users/me'.get
$has401 = $meOp.responses.PSObject.Properties.Name -contains "401"
if ($has401) { Write-Output "       [PASS] GET /users/me documents 401" } else { Write-Output "       [FAIL] 401 not documented" ; $script:fail_count++ }

# --- 10. database truth ----------------------------------------------------
Write-Output ""
Write-Output "-- 10. DATABASE TRUTH (psql via compose) ----------------------------"
Write-Output "       user row:  $(docker compose exec -T db psql -U hermedisafe -d hermedisafe -tAc "SELECT id||' | '||email||' | deleted_at='||COALESCE(deleted_at::text,'NULL') FROM users WHERE email='$email'")"
Write-Output "       profile:   $(docker compose exec -T db psql -U hermedisafe -d hermedisafe -tAc "SELECT 'id='||id||' deleted_at='||COALESCE(deleted_at::text,'NULL') FROM user_profiles WHERE user_id=$userId")"
$visible = docker compose exec -T db psql -U hermedisafe -d hermedisafe -tAc "SELECT count(*) FROM users WHERE deleted_at IS NULL"
Check "visible (non-tombstoned) users" ([int]$visible.Trim()) 0 "hidden by the global filter"
$audits = docker compose exec -T db psql -U hermedisafe -d hermedisafe -tAc "SELECT action FROM audit_logs ORDER BY id"
Write-Output "       audit trail (retained after deletion):"
$audits | ForEach-Object { Write-Output "         $_" }
$expected = @(
    "auth.signup",             # 1. signup
    "auth.signup_failed",      # 2. duplicate email
    "auth.login",              # 4. successful login
    "auth.login_failed",       # 4. wrong password
    "auth.login_failed",       # 4. unknown email
    "user.profile.read",       # 5. GET /users/me
    "user.profile.read",       # 5. 200-challenge check (also an authenticated GET)
    "user.profile.created",    # 6. first profile write
    "user.profile.updated",    # 6. second profile write
    "user.consent.recorded",   # 7. consent
    "user.profile.read",       # 8. GET /users/me before delete
    "user.account.soft_deleted",# 8. DELETE /users/me
    "auth.login_failed"        # 8. login after deletion
)
$actual = @($audits | ForEach-Object { $_.Trim() })
if (($actual -join "|") -eq ($expected -join "|")) {
    Write-Output "       [PASS] exact action sequence: one entry per state-changing call,"
    Write-Output "              plus a *_failed entry for each rejected attempt"
    $script:pass_count++
} else {
    Write-Output "       [FAIL] expected:"
    $expected | ForEach-Object { Write-Output "         $_" }
    $script:fail_count++
}
Write-Output ""
Write-Output "===================================================================="
Write-Output " RESULT: $($script:pass_count) passed, $($script:fail_count) failed"
Write-Output "===================================================================="
if ($script:fail_count -gt 0) { exit 1 }
