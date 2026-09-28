# End-to-end walkthrough: upload -> OCR -> review -> reconcile.
#
# Mirrors the user journey from the brief, over real HTTP against a real server,
# and prints the interesting parts of every response. Uses curl.exe because
# PowerShell's `curl` is an alias for Invoke-WebRequest, whose quoting rules for
# JSON bodies on Windows are a reliable source of silent 400s.
#
# Usage:  .\e2e_prescription.ps1
# Assumes: Postgres via `docker compose up -d db`, migrations applied, and
#          nothing listening on 8012.

$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8012"
$passed = 0
$failed = 0
$failures = New-Object System.Collections.ArrayList

function Curl([string[]]$argv) {
    # -s silences the progress meter, -S keeps errors visible.
    & curl.exe @argv
}

function Check([string]$name, [bool]$condition, [string]$detail = "") {
    if ($condition) {
        $script:passed++
        Write-Host "  [PASS] $name" -ForegroundColor Green
    }
    else {
        $script:failed++
        $null = $script:failures.Add($name)
        Write-Host "  [FAIL] $name $detail" -ForegroundColor Red
    }
}

function Section([string]$title) {
    Write-Host ""
    Write-Host "== $title ==" -ForegroundColor Cyan
}

# --------------------------------------------------------------------------
Section "0. health"
$health = Curl @("-sS", "$base/health") | ConvertFrom-Json
Check "api is up ($($health.status))" ($health.status -eq "ok" -or $health.status -eq "degraded") "got $($health.status)"

# --------------------------------------------------------------------------
Section "1. register a user"
$email = "e2e-$([guid]::NewGuid().ToString('N').Substring(0,10))@example.com"
$signupBody = '{\"email\":\"' + $email + '\",\"password\":\"Str0ngPassw0rd!\",\"full_name\":\"Asha Rao\"}'
# Backticks are PowerShell's escape char, so JSON quotes are escaped here and
# every other layer passes them through untouched.
$signupBody = $signupBody.Replace('\"', '"')
$signup = Curl @("-sS", "-X", "POST", "$base/auth/signup", "-H", "Content-Type: application/json", "-d", $signupBody) | ConvertFrom-Json
$token = $signup.access_token
Check "signup returned a token" ([bool]$token) "no access_token in response"
$auth = @("-H", "Authorization: Bearer $token")

# --------------------------------------------------------------------------
Section "2. upload a prescription image"
# Written as bytes rather than a real photograph: the endpoint sniffs content,
# so a valid PNG header is all it needs to accept the file.
$pngPath = Join-Path $env:TEMP "rx-sample.png"
[System.IO.File]::WriteAllBytes($pngPath, [byte[]](0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A) + (New-Object byte[] 512))

$uploadRaw = Curl @("-sS", "-X", "POST", "$base/prescriptions/upload") + $auth + @(
    "-F", "file=@$pngPath;type=image/png"
)
$upload = $uploadRaw | ConvertFrom-Json
$rxId = $upload.id
Check "upload returned 201 with an id" ($rxId -gt 0) "body: $($uploadRaw -join '')"
Check "file_url is served under /files" ($upload.file_url -like "/files/prescriptions/*") "got $($upload.file_url)"
Check "file_type detected from content" ($upload.file_type -eq "image") "got $($upload.file_type)"

$fetched = Curl @("-sS", "-o", "NUL", "-w", "%{http_code}", "$base$($upload.file_url)")
Check "the file is actually retrievable at its URL" ($fetched -eq "200") "got HTTP $fetched"

# --------------------------------------------------------------------------
Section "3. reject a non-prescription upload"
$badPath = Join-Path $env:TEMP "not-an-image.png"
[System.IO.File]::WriteAllText($badPath, "this is plainly not an image")
$badRaw = Curl @("-sS", "-o", "NUL", "-w", "%{http_code}", "-X", "POST", "$base/prescriptions/upload") + $auth + @("-F", "file=@$badPath;type=image/png")
Check "a non-image upload is refused with 415" ($badRaw -eq "415") "got HTTP $badRaw"

$anon = Curl @("-sS", "-o", "NUL", "-w", "%{http_code}", "$base/medicines")
Check "an unauthenticated read is refused with 401" ($anon -eq "401") "got HTTP $anon"

# --------------------------------------------------------------------------
Section "4. seed mock OCR results"
$ocr = Curl @("-sS", "-X", "POST", "$base/prescriptions/$rxId/mock-ocr") + $auth | ConvertFrom-Json
Check "three proposed medicines" ($ocr.medicines.Count -eq 3) "got $($ocr.medicines.Count)"
Check "all three await review" ($ocr.pending_review_count -eq 3) "got $($ocr.pending_review_count)"
foreach ($m in $ocr.medicines) {
    Write-Host ("     - {0,-22} confirmed={1} ingredient={2}" -f $m.raw_name, $m.is_confirmed, $m.normalized_ingredient)
}

$queue = Curl @("-sS", "$base/medicines/pending-review") + $auth | ConvertFrom-Json
Check "the review queue holds all three" ($queue.Count -eq 3) "got $($queue.Count)"

# --------------------------------------------------------------------------
Section "5. confirm the first medicine, correcting one field"
$crocin = $queue | Where-Object { $_.raw_name -eq "Crocin 500mg" }
$confirmBody = '{\"raw_name\":\"Crocin 500mg\",\"strength\":\"500mg\"}'.Replace('\"', '"')
$crocinOut = Curl @("-sS", "-X", "PATCH", "$base/medicines/$($crocin.id)/confirm") + $auth + @(
    "-H", "Content-Type: application/json", "-d", $confirmBody
) | ConvertFrom-Json
Check "Crocin is confirmed" ($crocinOut.is_confirmed -eq $true)
Check "Crocin normalised to Paracetamol" ($crocinOut.normalized_ingredient -eq "Paracetamol") "got '$($crocinOut.normalized_ingredient)'"
Check "the extractor's confidence is cleared" ($null -eq $crocinOut.confidence_score) "got $($crocinOut.confidence_score)"
Check "unsupplied fields survived" ($crocinOut.frequency -eq "twice daily") "got '$($crocinOut.frequency)'"

$noDupYet = Curl @("-sS", "$base/medicines/duplicates") + $auth | ConvertFrom-Json
Check "no duplicate while there is only one Paracetamol" ($noDupYet.Count -eq 0) "got $($noDupYet.Count)"

# --------------------------------------------------------------------------
Section "6. reject the unrecognised line"
$queue = Curl @("-sS", "$base/medicines/pending-review") + $auth | ConvertFrom-Json
$tonic = $queue | Where-Object { $_.raw_name -eq "Herbal Liver Tonic" }
$rejectBody = '{\"reason\":\"a supplement, not part of this prescription\"}'.Replace('\"', '"')
$tonicOut = Curl @("-sS", "-X", "PATCH", "$base/medicines/$($tonic.id)/reject") + $auth + @(
    "-H", "Content-Type: application/json", "-d", $rejectBody
) | ConvertFrom-Json
Check "the tonic is marked rejected" ($tonicOut.status -eq "rejected") "got $($tonicOut.status)"

$queue = Curl @("-sS", "$base/medicines/pending-review") + $auth | ConvertFrom-Json
Check "it left the review queue" ($queue.Count -eq 1) "got $($queue.Count)"

# --------------------------------------------------------------------------
Section "7. confirm Dolo, a different brand of the same ingredient"
$dolo = $queue | Where-Object { $_.raw_name -eq "Dolo 650" }
$doloBody = '{\"raw_name\":\"Dolo 650\",\"strength\":\"650mg\"}'.Replace('\"', '"')
$doloOut = Curl @("-sS", "-X", "PATCH", "$base/medicines/$($dolo.id)/confirm") + $auth + @(
    "-H", "Content-Type: application/json", "-d", $doloBody
) | ConvertFrom-Json
Check "Dolo normalised to the same ingredient" ($doloOut.normalized_ingredient -eq "Paracetamol") "got '$($doloOut.normalized_ingredient)'"

# --------------------------------------------------------------------------
Section "8. duplicate detection fired"
$dups = Curl @("-sS", "$base/medicines/duplicates") + $auth | ConvertFrom-Json
Check "one duplicate pair is flagged" ($dups.Count -eq 1) "got $($dups.Count)"
if ($dups.Count -eq 1) {
    $flag = $dups[0]
    Write-Host "     pair: [$($flag.medicine_a.brand_name) $($flag.medicine_a.strength)] vs [$($flag.medicine_b.brand_name) $($flag.medicine_b.strength)]  -> $($flag.medicine_a.normalized_ingredient)"
    $ids = @($flag.medicine_a.id, $flag.medicine_b.id)
    Check "the pair is Crocin and Dolo" ($ids -contains $crocinOut.id -and $ids -contains $doloOut.id) "got $($ids -join ',')"
    Check "the flag starts unresolved" ($flag.resolved -eq $false)

    Section "9. resolve it as 'keep both'"
    $resolveBody = '{\"resolution\":\"keep_both\",\"note\":\"two strengths, both prescribed\"}'.Replace('\"', '"')
    $resolved = Curl @("-sS", "-X", "PATCH", "$base/medicines/duplicates/$($flag.id)/resolve") + $auth + @(
        "-H", "Content-Type: application/json", "-d", $resolveBody
    ) | ConvertFrom-Json
    Check "the flag is resolved" ($resolved.resolved -eq $true)
    Check "nothing was removed" ($null -eq $resolved.removed_medicine_id)
}

# --------------------------------------------------------------------------
Section "10. the confirmed list"
$confirmed = Curl @("-sS", "$base/medicines?confirmed=true") + $auth | ConvertFrom-Json
Check "two confirmed medicines" ($confirmed.Count -eq 2) "got $($confirmed.Count)"
foreach ($m in $confirmed) {
    Write-Host ("     - {0,-16} {1,-10} source={2} confidence={3}" -f $m.raw_name, $m.normalized_ingredient, $m.source, $m.confidence_score)
}
Check "both carry a normalised ingredient" (($confirmed | Where-Object { -not $_.normalized_ingredient }).Count -eq 0)
Check "both are attributed to the prescription" (($confirmed | Where-Object { $_.source -ne "prescription" }).Count -eq 0)

# --------------------------------------------------------------------------
Section "11. a manual entry also collides"
$manualBody = '{\"raw_name\":\"Calpol 650\",\"strength\":\"650mg\"}'.Replace('\"', '"')
$manual = Curl @("-sS", "-X", "POST", "$base/medicines") + $auth + @(
    "-H", "Content-Type: application/json", "-d", $manualBody
) | ConvertFrom-Json
Check "the manual entry is confirmed on creation" ($manual.is_confirmed -eq $true)
Check "and normalised to the same ingredient" ($manual.normalized_ingredient -eq "Paracetamol") "got '$($manual.normalized_ingredient)'"
Check "and attributed to self-report, not a prescription" ($manual.source -eq "self_reported") "got $($manual.source)"

$dups = Curl @("-sS", "$base/medicines/duplicates") + $auth | ConvertFrom-Json
Check "the manual entry is flagged against both" ($dups.Count -eq 2) "got $($dups.Count)"

# --------------------------------------------------------------------------
Section "12. cross-user isolation"
$otherEmail = "e2e-$([guid]::NewGuid().ToString('N').Substring(0,10))@example.com"
$otherBody = ('{{"email":"{0}","password":"Str0ngPassw0rd!","full_name":"Other User"}}' -f $otherEmail)
$other = Curl @("-sS", "-X", "POST", "$base/auth/signup", "-H", "Content-Type: application/json", "-d", $otherBody) | ConvertFrom-Json
$otherAuth = @("-H", "Authorization: Bearer $($other.access_token)")

$otherList = Curl @("-sS", "$base/prescriptions") + $otherAuth | ConvertFrom-Json
Check "the other user sees no uploads" ($otherList.total -eq 0) "got $($otherList.total)"
$steal = Curl @("-sS", "-o", "NUL", "-w", "%{http_code}", "$base/prescriptions/$rxId") + $otherAuth
Check "the other user cannot read this upload (404, not 403)" ($steal -eq "404") "got HTTP $steal"
$stealDups = Curl @("-sS", "$base/medicines/duplicates") + $otherAuth | ConvertFrom-Json
Check "the other user sees no duplicates" ($stealDups.Count -eq 0) "got $($stealDups.Count)"

# --------------------------------------------------------------------------
Section "13. delete the prescription"
$before = Curl @("-sS", "$base/prescriptions") + $auth | ConvertFrom-Json
Check "one upload before deletion" ($before.total -eq 1)
$fileUrl = $before.items[0].file_url

$del = Curl @("-sS", "-o", "NUL", "-w", "%{http_code}", "-X", "DELETE", "$base/prescriptions/$rxId") + $auth
Check "delete succeeded" ($del -eq "200") "got HTTP $del"

$after = Curl @("-sS", "$base/prescriptions") + $auth | ConvertFrom-Json
Check "the upload is gone from the list" ($after.total -eq 0) "got $($after.total)"
$gone = Curl @("-sS", "-o", "NUL", "-w", "%{http_code}", "$base$fileUrl")
Check "and the file is gone from storage" ($gone -eq "404") "got HTTP $gone"

$remaining = Curl @("-sS", "$base/medicines?confirmed=true") + $auth | ConvertFrom-Json
Check "its medicines were cascaded away" ($remaining.Count -eq 1) "got $($remaining.Count)"
Check "the hand-typed medicine survived" ($remaining[0].id -eq $manual.id) "got $($remaining[0].id), expected $($manual.id)"

# --------------------------------------------------------------------------
Section "14. account erasure reaches the new data too"
$erase = Curl @("-sS", "-X", "DELETE", "$base/users/me") + $auth | ConvertFrom-Json
Check "the account is soft-deleted" ($null -ne $erase.deleted_at)
$afterErase = Curl @("-sS", "-o", "NUL", "-w", "%{http_code}", "$base/medicines") + $auth
Check "its token no longer works" ($afterErase -eq "401") "got HTTP $afterErase"

# --------------------------------------------------------------------------
Write-Host ""
Write-Host "===================================================" -ForegroundColor Cyan
if ($failed -eq 0) {
    Write-Host " RESULT: $passed passed, 0 failed" -ForegroundColor Green
}
else {
    Write-Host " RESULT: $passed passed, $failed FAILED" -ForegroundColor Red
    foreach ($f in $failures) { Write-Host "   - $f" -ForegroundColor Red }
}
Write-Host "===================================================" -ForegroundColor Cyan

if ($failed -gt 0) { exit 1 }
