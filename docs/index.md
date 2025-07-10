---
title: "warcex"
---

WARCEX is an extensible command-line tool for extracting structured data out of WARC and WACZ files. 

WARCex is an ARDC-funded work package under the Australian Internet Observatory.

## Installation

Install from GitHub using it pip:
```bash
pip install +git://github.com/QUT-Digital-Observatory/warcex.git
```


## Usage

To get an overview of available commands, run:
```bash
warcex --help
```

You can see what plugins are available by running:

```bash
warcx plugins
```

And you can get more information about a plugin including instructions on web archiving activity by running:

```bash
warcx info <plugin-name>
```

Extracting data:

```bash
warcx --plugin fb-groups extract my_input_file.wacz my_output_folder/
```
You can specify more than one.
