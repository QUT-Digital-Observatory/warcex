---
title: "warcex"
---

WARCEX is an extensible command-line tool for extracting structured data out of WARC and WACZ files, developed by the [Digital Observatory](https://www.digitalobservatory.net.au/), as part of the [Australian Internet Observatory (AIO)](https://internetobservatory.org.au/).

AIO received co-investment ([doi.org/10.3565/hjrp-b141](https://doi.org/10.3565/hjrp-b141)) from the Australian Research Data Commons (ARDC) through the [HASS and Indigenous Research Data Commons](https://ardc.edu.au/hass-and-indigenous-research-data-commons/). The ARDC is enabled by the National Collaborative Research Infrastructure Strategy (NCRIS).

![](images/ardc-banner-logo.svg)


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
warcex plugins
```

And you can get more information about a plugin including instructions on web archiving activity by running:

```bash
warcex info <plugin-name>
```

Extracting data:

```bash
warcex --plugin fb-groups extract my_input_file.wacz my_output_folder/
```
You can specify more than one.
