# carddav-utils
Python tooling for my personal CardDav needs.

## Scope & Goal

### Profile Picture Crawling

* Interface for crawling profile pictures from different sources. Currently implemented:
  * Telegram via User Bot API
  * Signal Desktop via [sigtop](https://github.com/tbvdm/sigtop)
  * Local directory with images named after the contact's phone number
* Storing crawled profile pictures on a NextCloud instance
* Inject crawled profile pictures into CardDav address books based on phone numbers

### Address Book Merging

* Merges several CardDav address books into one *without deleting* any existing contacts. Target is to gather all contacts from several address books into one without losing any data that may be deleted in the source address books.
* Tailored for and tested with [NextCloud](https://nextcloud.com) CardDav address books.
* Assumes that UIDs of contacts are unique across all address books.
* Does not consider changes made to contacts in the target address book. Those will be overwritten by the contacts from the source address books on the next sync.
* Support for enriching contacts with crawled profile pictures and additional information (phone numbers, email addresses) before merge. Data is downloaded from NextCloud storage.

## Usage

* Clone the repository
* `pip install .`
* `python -m carddav_utils --help`

## Status and Contributing

This is your usual "let me quickly set up an automation that works for me" project.
It works for me and I don't currently have any plans to extend it.
However, if it's useful for you and you want to contribute, feel free to open an issue or a pull request.

## Diagram

```mermaid
graph TD
    Injector[Profile Picture Injector]
    Uploader[Profile Picture Uploader]
    Enricher[Contact Enricher]
    NextCloudStorage[NextCloud Storage Interface]
    
    subgraph NextCloud[NextCloud Instance]
        direction TB
        subgraph NextCloudStorage[NextCloud Storage]
            direction TB
            PictureStorage[Crawled Profile Pictures]
            AdditionalInfoStorage[Additional Contact Info]
        end
        subgraph AddressBooks[CardDav Address Books]
            direction TB
            Source1[Source Address Book 1]
            Source2[Source Address Book 2]
            InjectionTarget1[Injection Target 1]
            InjectionTarget2[Injection Target 2]
            MergeTarget1[Merge Target 1]
            MergeTarget2[Merge Target 2]
        end
    end
    
    subgraph Crawlers[Profile Picture Crawlers]
        direction TB
        Telegram[Telegram Crawler]
        Signal[Signal Crawler]
        Local[Local Directory Crawler]
    end
    
    subgraph Merger[Address Book Merger]
        direction TB
        MergingLogic[Merging Logic]
    end
    
    Crawlers --> |python -m carddav_utils upload-profile-pictures|Uploader --> NextCloudStorage
    Crawlers --> |python -m carddav_utils inject-profile-pictures|Injector
    Injector --> InjectionTarget1
    Injector --> InjectionTarget2
    NextCloudStorage --> Enricher --> MergingLogic
    Source1 --> MergingLogic
    Source2 --> MergingLogic
    MergingLogic --> |python -m carddav_utils merge-address-books|MergeTarget1
    MergingLogic --> |python -m carddav_utils merge-address-books|MergeTarget2
```
