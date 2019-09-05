#!/usr/bin/env python3
from plumbum import cli
import re
import sh
from pathlib import Path, PurePath
import shutil
import os
import rdfind
import mmap


templatesDir = Path("./templates")
patchFileTemplatePath = Path(templatesDir / "Fixed-bug_in_MinGW_rpcndr.patch.templ")
patchFileTemplate = patchFileTemplatePath.read_text()

cmakeToolchainFileTemplatePath = Path(templatesDir / "toolchain.cmake.templ")
cmakeToolchainFileTemplate = cmakeToolchainFileTemplatePath.read_text()

archs = {
	"x86_64": "64",
	"i686": "32"
}


currentProcFileDescriptors = Path("/proc") / str(os.getpid()) / "fd"
fj = sh.firejail.bake(noblacklist=str(currentProcFileDescriptors), _fg=True)

#aria2c = fj.aria2c.bake(_fg=True, **{"continue": "true", "check-certificate": "true", "enable-mmap": "true", "optimize-concurrent-downloads": "true", "j": 16, "x": 16, "file-allocation": "falloc"})
aria2c = sh.Command("/usr/bin/aria2c").bake(_fg=True, **{"continue": "true", "check-certificate": "true", "enable-mmap": "true", "optimize-concurrent-downloads": "true", "j": 16, "x": 16, "file-allocation": "falloc"})


def download(targets):
	return
	args = []

	for dst, uri in targets.items():
		args += [uri, os.linesep, " ", "out=", str(dst), os.linesep]

	pO, pI = os.pipe()
	with os.fdopen(pI, "w") as pIF:
		pIF.write("".join(args))
		pIF.flush()
	try:
		aria2c(**{"input-file": str(currentProcFileDescriptors / str(pO))})
	finally:
		os.close(pO)
		try:
			os.close(pI)
		except BaseException:
			pass


def movetree(src, dst):
	if src.is_dir():
		dst.mkdir(parents=True, exist_ok=True)
		for f in src.iterdir():
			targetName = dst / f.name
			if f.is_dir() and targetName.exists():
				movetree(f, targetName)
				f.rmdir()
			else:
				f.rename(targetName)
	else:
		dst.parent.mkdir(parents=True, exist_ok=True)
		src.rename(dst)


def gitPatch(patchText, dir):
	pO, pI = os.pipe()
	with os.fdopen(pI, "w") as pIF:
		pIF.write(patchText)
		pIF.flush()
	try:
		sh.git.apply(str(currentProcFileDescriptors / str(pO)), **{"ignore-whitespace": True, "_cwd": dir})
	except Exception as ex:
		print(ex)
	finally:
		os.close(pO)
		try:
			os.close(pI)
		except BaseException:
			pass


def justPatch(patchText, fileToPatch):
	sh.patch(fileToPatch, **{"ignore-whitespace": True, "_in": patchText})


def sevenZArgsProcessor(args, kwargs):
	argz = []
	kwargz = {}
	for k, v in kwargs.items():
		if isinstance(v, bool):
			kwargz[k] = v
		else:
			argz.append("-" + k + str(v))
	argz.extend(args)
	return argz, kwargz


sevenZ = sh.Command("7z").bake(_arg_preprocess=sevenZArgsProcessor, _long_prefix="-", _long_sep=" ")

# WARNING: If you have errors like
# `undefined reference to `_Unwind_Resume'`
# `undefined reference to `__gxx_personality_v0'
# you probably have mixed dwarf with sjlj


def createToolchainFromMingwW64Packages(outPath):
	gccVersion = "8.1.0"
	files2Download = {
		# "mingw32.7z":"https://netix.dl.sourceforge.net/project/mingw-w64/Toolchains%20targetting%20Win32/Personal%20Builds/mingw-builds/8.1.0/threads-posix/sjlj/i686-8.1.0-release-posix-sjlj-rt_v6-rev0.7z",
		"mingw32.7z": "https://datapacket.dl.sourceforge.net/project/mingw-w64/Toolchains%20targetting%20Win32/Personal%20Builds/mingw-builds/8.1.0/threads-posix/dwarf/i686-8.1.0-release-posix-dwarf-rt_v6-rev0.7z",
		"mingw64.7z": "https://netix.dl.sourceforge.net/project/mingw-w64/Toolchains%20targetting%20Win64/Personal%20Builds/mingw-builds/8.1.0/threads-posix/seh/x86_64-8.1.0-release-posix-seh-rt_v6-rev0.7z",
	}
	sourceforgeDir = Path("./sf")
	#if sourceforgeDir.exists():
	#	shutil.rmtree(str(sourceforgeDir))
	sourceforgeDir.mkdir(parents=True, exist_ok=True)

	download({(sourceforgeDir / fn): uri for fn, uri in files2Download.items()})

	unpackedDir = Path("./unpacked")
	if unpackedDir.exists():
		shutil.rmtree(str(unpackedDir))
	unpackedDir.mkdir(parents=True, exist_ok=True)

	for arch, archBitness in archs.items():
		archToolchainName = "mingw" + archBitness
		sevenZ("x", sourceforgeDir / (archToolchainName + ".7z"), o=unpackedDir)
		toolchainPath = unpackedDir / (archToolchainName)
		archDirName = arch + "-w64-mingw32"
		for fn in ("bin", "etc", "libexec", "share", "opt/bin", "opt/info", "opt/share", "opt/lib/python2.7", "opt/ssl", archDirName + "/bin"):
			shutil.rmtree(str(toolchainPath / fn))
		movetree(toolchainPath, outPath)
	return gccVersion


def createToolchainFromFedoraPackages(outPath):
	fedoraPackagesURI = "https://dl.fedoraproject.org/pub/fedora/linux/development/31/Everything/x86_64/os/Packages/m/"
	files2Download = {
		"mingw64-cpp.rpm": "mingw64-cpp-9.1.1-2.fc31.x86_64.rpm",
		"mingw64-gcc.rpm": "mingw64-gcc-9.1.1-2.fc31.x86_64.rpm",
		"mingw64-gcc-c++.rpm": "mingw64-gcc-c++-9.1.1-2.fc31.x86_64.rpm",
		"mingw64-gcc-gfortran.rpm": "mingw64-gcc-gfortran-9.1.1-2.fc31.x86_64.rpm",
		"mingw64-headers.rpm": "mingw64-headers-6.0.0-2.fc31.noarch.rpm",
		"mingw64-crt.rpm": "mingw64-crt-6.0.0-2.fc31.noarch.rpm",
		"mingw64-binutils.rpm": "mingw64-binutils-2.32-3.fc31.x86_64.rpm",
		"mingw64-winpthreads.rpm": "mingw64-winpthreads-6.0.0-2.fc31.noarch.rpm",
		
		"mingw32-cpp.rpm": "mingw32-cpp-9.1.1-2.fc31.x86_64.rpm",
		"mingw32-gcc.rpm": "mingw32-gcc-9.1.1-2.fc31.x86_64.rpm",
		"mingw32-gcc-c++.rpm": "mingw32-gcc-c++-9.1.1-2.fc31.x86_64.rpm",
		"mingw32-gcc-gfortran.rpm": "mingw32-gcc-gfortran-9.1.1-2.fc31.x86_64.rpm",
		"mingw32-headers.rpm": "mingw32-headers-6.0.0-2.fc31.noarch.rpm",
		"mingw32-crt.rpm": "mingw32-crt-6.0.0-2.fc31.noarch.rpm",
		"mingw32-binutils.rpm": "mingw32-binutils-2.32-3.fc31.x86_64.rpm",
		"mingw32-winpthreads.rpm": "mingw32-winpthreads-6.0.0-2.fc31.noarch.rpm"
	}

	rpmsDir = Path("./rpms")
	#download({(rpmsDir/fn):(fedoraPackagesURI+rfn) for fn, rfn in files2Download.items()})

	alien = sh.Command("alien")
	rpmsUnpacked = Path("./rpmsUnpacked")

	rpms = [p.absolute() for p in rpmsDir.glob("*.rpm")]

	if rpmsUnpacked.exists():
		shutil.rmtree(str(rpmsUnpacked))
	rpmsUnpacked.mkdir(parents=True, exist_ok=True)
	alien(rpms, g=True, _cwd=rpmsUnpacked)

	for d in rpmsUnpacked.iterdir():
		if d.suffix == ".orig":
			movetree(d / "usr", outPath)

	gccVersion = "9.1.1"

	for arch in archs:
		archDirName = arch + "-w64-mingw32"
		archDir = outPath / archDirName
		mingwDir = archDir / "sys-root" / "mingw"
		lgccDir = outPath / "lib" / "gcc" / archDirName
		lgccInclude = lgccDir / gccVersion / "include"
		lgccLib = lgccDir / "lib"
		movetree(mingwDir, archDir)

		for fn in (archDir / "bin",):
			shutil.rmtree(str(fn))

		movetree(archDir / "include" / "c++", lgccInclude / "c++")
		movetree(lgccInclude / "c++" / archDirName, lgccInclude / "c++")

		#for fn in ("libgcc_s.a", ):
		#	movetree(archDir / "lib" / fn, lgccLib / fn)

	for fn in ("bin", "libexec", "share"):
		shutil.rmtree(str(outPath / fn))

	return gccVersion


patchRxSrc = r"(\s*)enum\s+class\s+byte\s*:\s*unsigned\s+char\s*;"
patchRx = re.compile(patchRxSrc.encode("utf-8"))


def patchToolchain(outPath, gccVersion):
	
	def patchDir(dir2Patch):
		patchesInDir = 0
		
		for p in dir2Patch.glob('**/*'):
			if p.is_file():
				with p.open("r+b") as f:
					s = None
					with mmap.mmap(f.fileno(), p.stat().st_size, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ, access=mmap.ACCESS_DEFAULT, offset=0) as mapping:
						m = patchRx.search(mapping)
						if m:
							s, count = patchRx.subn(lambda m: m.group(0) + b"\n" + m.group(1) + b"#define _BYTE_DEFINED_AdTydTeKkpRvvDuzZisXJMGxPRSHkr", mapping)
							if count != 1:
								raise Exception("FUCK, `count` is not 1, but " + str(count) + " so the result may be broken!")
					if s:
						f.seek(0)
						f.write(s)
						patchesInDir += count
		return patchesInDir

	for arch in archs:
		archDirName = arch + "-w64-mingw32"
		#gitPatch(patchFileTemplate.replace("$ARCH", arch), outPath) # doesn't work IDK why after I have changed something in it
		justPatch(patchFileTemplate.replace("$ARCH", arch), outPath / archDirName / "include" / "rpcndr.h")
		
		patchesInCPPHeadersForArch = 0
		for d in ((outPath / archDirName / "include"), (outPath / "lib" / "gcc" / archDirName)):
			patchesInCPPHeadersForArch += patchDir(d)
		
		if not patchesInCPPHeadersForArch:
			raise Exception("FUCK, count of patches in C++ headers for arch " + arch + " is less than 1, but " + str(patchesInCPPHeadersForArch) + " so the result may be broken!")


def createCMakeToolchainFile(dst, toolchainPath, arch):
	dst.write_text(cmakeToolchainFileTemplate.replace("$$TOOLCHAIN_PATH$$", str(toolchainPath)).replace("$$ARCH$$", arch))


def createCMakeToolchainFiles(outPath):
	for arch in archs:
		createCMakeToolchainFile(outPath / ("mingw-w64-" + arch + "-toolchain.cmake"), outPath, arch)


class ToolchainCreatorCLI(cli.Application):
	def main(self):
		outPath = Path("./toolchain")
		if outPath.exists():
			shutil.rmtree(str(outPath))

		outPath.mkdir(parents=True, exist_ok=True)

		#gccVersion = createToolchainFromFedoraPackages(outPath)
		gccVersion = createToolchainFromMingwW64Packages(outPath)
		patchToolchain(outPath, gccVersion)
		# todo: make it create non-absolute symlinks
		rdfind.dedup("./toolchain")
		createCMakeToolchainFiles(outPath)


if __name__ == "__main__":
	ToolchainCreatorCLI.run()
